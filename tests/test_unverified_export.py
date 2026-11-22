import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from tarveri.cogs.admin_dashboard_actions import DashboardActionsMixin
from tarveri.database import Database
from tarveri.services.unverified_export import (
    build_unverified_csv,
    collect_unverified_members,
    package_export,
)

NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _role(rid, name, default=False):
    return SimpleNamespace(id=rid, name=name, is_default=lambda: default)


class _Member(SimpleNamespace):
    def __str__(self):
        return self.display_name


def _member(mid, name, days_ago, roles=(), bot=False):
    return _Member(
        id=mid,
        bot=bot,
        display_name=name,
        joined_at=NOW - timedelta(days=days_ago),
        created_at=NOW - timedelta(days=900),
        roles=[_role(1, "@everyone", default=True), *roles],
    )


def _members():
    guest = _role(50, "Guest")
    return [
        _member(1, "verified", 30),
        _member(2, "newbie", 2),
        _member(3, "=HYPERLINK(evil)", 40, roles=[guest]),
        _member(4, "botty", 100, bot=True),
    ]


def test_collect_skips_bots_and_verified_and_sorts_longest_waiting_first():
    rows = collect_unverified_members(_members(), verified_ids={1}, guest_role_id=50)
    assert [u.discord_user_id for u in rows] == [3, 2]
    assert rows[0].is_guest and rows[0].roles == ["Guest"]
    assert not rows[1].is_guest and rows[1].roles == []


def test_csv_has_header_and_neutralises_formulas():
    rows = collect_unverified_members(_members(), verified_ids={1}, guest_role_id=50)
    text = build_unverified_csv(rows, NOW).decode("utf-8-sig")
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[0][0] == "discord_user_id"
    assert parsed[1][2] == "'=HYPERLINK(evil)"
    assert parsed[1][4] == "40" and parsed[1][6] == "yes"
    assert parsed[2][0] == "2"


def test_package_zips_when_over_limit_and_gives_up_when_still_too_big():
    data = b"a,b\n" * 5000
    assert package_export(data, "x", limit=len(data)) == (data, "x.csv")
    zipped, name = package_export(data, "x", limit=len(data) - 1)
    assert name == "x.zip"
    assert zipfile.ZipFile(io.BytesIO(zipped)).read("x.csv") == data
    assert package_export(data, "x", limit=10) is None


@pytest.mark.asyncio
async def test_get_verified_user_ids(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    try:
        await db.record_verification(123, "hash1", "FOCS")
        assert await db.get_verified_user_ids() == {123}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_dashboard_export_sends_embed_with_csv_and_logs():
    db = MagicMock()
    db.get_verified_user_ids = AsyncMock(return_value={1})
    db.get_guild_settings = AsyncMock(return_value=(None, None, "Guest"))
    db.log = AsyncMock()
    guest_service = SimpleNamespace(find_guest_role=AsyncMock(return_value=_role(50, "Guest")))
    view = DashboardActionsMixin()
    view.cog = SimpleNamespace(db=db, bot=SimpleNamespace(guest_service=guest_service))

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.guild = SimpleNamespace(id=9, chunked=True, members=_members(), filesize_limit=10 * 1024 * 1024)
    interaction.user = SimpleNamespace(id=7)

    await view._on_unverified_export_clicked(interaction)

    kwargs = interaction.followup.send.call_args.kwargs
    assert "**2** of **3**" in kwargs["embed"].description
    assert kwargs["file"].filename.endswith(".csv")
    db.log.assert_awaited_once()
    assert db.log.call_args.args[1] == "ADMIN_UNVERIFIED_EXPORT"
