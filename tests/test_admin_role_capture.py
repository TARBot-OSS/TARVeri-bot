"""
Tests for the one-time capture of each guild's admin role by ID, and the ID-based admin check.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

from tarveri.bot import TARVeriBot
from tarveri.config import Settings
from tarveri.database import Database
from tarveri.views.guest_views import is_admin_or_has_role, pick_admin_role_to_capture


def _role(role_id: int, name: str, perms: discord.Permissions | None = None) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.name = name
    role.permissions = perms or discord.Permissions.none()
    role.is_default.return_value = False
    return role


def _interaction(guild_id: int, roles: list, guild_roles: list, admin_role_ids: dict) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = guild_id
    interaction.guild.roles = guild_roles
    member = MagicMock(spec=discord.Member)
    member.guild_permissions = discord.Permissions.none()
    member.roles = roles
    interaction.user = member
    interaction.client = SimpleNamespace(db=SimpleNamespace(admin_role_ids=admin_role_ids))
    return interaction


def test_captured_role_id_is_trusted_and_same_name_copy_is_not():
    real = _role(100, "TARVeri Admin")  # no Discord permissions, the current setup
    spoof = _role(900, "TARVeri Admin")  # created later by a moderator
    guild_roles = [real, spoof]

    assert is_admin_or_has_role(_interaction(1, [real], guild_roles, {1: 100}), "TARVeri Admin") is True
    assert is_admin_or_has_role(_interaction(1, [spoof], guild_roles, {1: 100}), "TARVeri Admin") is False
    # Without a captured ID the permission rule applies, so the no-permission role is not trusted.
    assert is_admin_or_has_role(_interaction(1, [real], guild_roles, {}), "TARVeri Admin") is False
    # 0 means "no trusted role": a role that happens to have ID 0 is never matched.
    assert is_admin_or_has_role(_interaction(1, [_role(0, "x")], guild_roles, {1: 0}), "TARVeri Admin") is False


def test_pick_admin_role_prefers_oldest_and_reports_duplicates():
    newer = _role(900, "TARVeri Admin")
    older = _role(100, "tarveri admin")
    other = _role(50, "Member")
    guild = MagicMock(spec=discord.Guild)
    guild.roles = [other, newer, older]

    role, duplicates = pick_admin_role_to_capture(guild, "TARVeri Admin")
    assert role is older
    assert duplicates == [newer]

    guild.roles = [other]
    assert pick_admin_role_to_capture(guild, "TARVeri Admin") == (None, [])


@pytest.mark.asyncio
async def test_admin_role_id_column_migrates_and_cache_tracks_writes(tmp_path):
    path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            "CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, admin_role_name TEXT, updated_at TEXT NOT NULL)"
        )
        await conn.execute("INSERT INTO guild_settings VALUES (1, 'TARVeri Admin', '')")
        await conn.commit()

    db = Database(path)
    await db.connect()
    try:
        assert db.admin_role_ids == {}  # legacy row: NULL, still to be captured
        await db.set_guild_admin_role_id(1, 100)
        await db.set_guild_admin_role_id(2, None)
        assert db.admin_role_ids == {1: 100, 2: 0}
        db.admin_role_ids = {}
        await db.load_admin_role_ids()
        assert db.admin_role_ids == {1: 100, 2: 0}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_capture_runs_once_per_guild_and_warns_on_duplicates():
    real = _role(100, "TARVeri Admin")
    spoof = _role(900, "TARVeri Admin")
    guild_a = MagicMock(spec=discord.Guild)
    guild_a.id, guild_a.name, guild_a.roles = 1, "A", [real, spoof]
    guild_b = MagicMock(spec=discord.Guild)
    guild_b.id, guild_b.name, guild_b.roles = 2, "B", [_role(5, "Member")]
    guild_c = MagicMock(spec=discord.Guild)
    guild_c.id, guild_c.name, guild_c.roles = 3, "C", [_role(7, "TARVeri Admin")]

    db = MagicMock()
    db.admin_role_ids = {3: 0}  # already decided: must not be captured again
    db.get_guild_settings = AsyncMock(return_value=None)
    db.set_guild_admin_role_id = AsyncMock()
    db.log = AsyncMock()
    bot = SimpleNamespace(
        guilds=[guild_a, guild_b, guild_c],
        db=db,
        settings=Settings(bot_token="t", id_hash_secret="s"),
    )

    await TARVeriBot.capture_admin_roles(bot)

    db.set_guild_admin_role_id.assert_any_await(1, 100)
    db.set_guild_admin_role_id.assert_any_await(2, 0)
    assert db.set_guild_admin_role_id.await_count == 2
    events = [c.args[1] for c in db.log.await_args_list]
    assert events == ["ADMIN_ROLE_CAPTURED", "ADMIN_ROLE_DUPLICATES"]
