"""
Tests for the admin dashboard's fuzzy student name search.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from cryptography.fernet import Fernet

from tarveri.cogs.admin_dashboard_modals import StudentNameSearchModal
from tarveri.config import decrypt_email, encrypt_email
from tarveri.database import Database
from tarveri.services.student_search import (
    extract_email_name,
    name_match_score,
    search_students_by_name,
)


def test_extract_email_name_strips_campus_year_suffix():
    assert extract_email_name("tan.wei.ming-wm24@student.tarc.edu.my") == "tan wei ming"
    assert extract_email_name("TanWeiMing-WM24@student.tarc.edu.my") == "tanweiming"
    assert extract_email_name("ali_bin-abu-pa23@student.tarc.edu.my") == "ali bin abu"
    assert extract_email_name("not-an-email") is None


@pytest.mark.parametrize("query", ["tan wei ming", "weiming tan", "tanweiming", "tan wei mng", "tam wei ming", "wei"])
def test_name_match_handles_order_spacing_partial_and_typos(query):
    assert name_match_score(query, "tan wei ming") >= 0.8
    assert name_match_score(query, "tanweiming") >= 0.8


@pytest.mark.parametrize("query", ["lim", "john", "chong kar wai"])
def test_name_match_rejects_unrelated_names(query):
    # Short words must match exactly, so "lim" does not near-match "ming".
    assert name_match_score(query, "tan wei ming") < 0.8


def test_search_ranks_filters_members_and_skips_bad_ciphertext():
    key = Fernet.generate_key().decode()

    def rec(uid, email):
        return (uid, "FOCS", "W", "R", False, encrypt_email(email, key))

    records = [
        rec(1, "tanweiming-wm24@student.tarc.edu.my"),
        rec(2, "tan.wei.min-wm23@student.tarc.edu.my"),
        rec(3, "limahkow-wm24@student.tarc.edu.my"),
        rec(4, "tanweiming-pa22@student.tarc.edu.my"),  # not a member of this server
        (5, "FOCS", "W", "R", False, "not-a-fernet-token"),
    ]
    matches = search_students_by_name("Tan Wei Ming", records, lambda c: decrypt_email(c, key), member_ids={1, 2, 3, 5})
    assert [m.discord_user_id for m in matches] == [1, 2]
    assert matches[0].score == 1.0
    assert matches[0].name == "tanweiming"


@pytest.mark.asyncio
async def test_get_email_verified_students_only_returns_rows_with_email(tmp_path):
    db = Database(str(tmp_path / "search.db"))
    await db.connect()
    try:
        await db._conn.execute(
            "INSERT INTO verifications (discord_user_id, student_id_hash, faculty_code, verified_at, "
            "campus_code, level_code, student_email_encrypted) VALUES (1, 'h1', 'FOCS', 'now', 'W', 'R', 'enc')"
        )
        await db._conn.execute(
            "INSERT INTO verifications (discord_user_id, student_id_hash, faculty_code, verified_at) "
            "VALUES (2, 'h2', 'FAFB', 'now')"
        )
        await db._conn.commit()
        assert await db.get_email_verified_students() == [(1, "FOCS", "W", "R", False, "enc")]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_name_search_modal_lists_matches_for_this_server_only():
    key = Fernet.generate_key().decode()
    email_service = SimpleNamespace(
        settings=SimpleNamespace(email_encryption_key=key),
        decrypt_student_email=lambda c: decrypt_email(c, key),
    )
    db = MagicMock()
    db.get_email_verified_students = AsyncMock(
        return_value=[
            (11, "FOCS", "W", "R", False, encrypt_email("tanweiming-wm24@student.tarc.edu.my", key)),
            (99, "FOCS", "W", "R", False, encrypt_email("tanweiming-pa22@student.tarc.edu.my", key)),
        ]
    )
    db.log = AsyncMock()
    cog = SimpleNamespace(bot=SimpleNamespace(email_service=email_service), db=db)

    modal = StudentNameSearchModal(cog, MagicMock())
    modal.name_query._value = "weiming tan"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.roles = []
    interaction.guild.members = [SimpleNamespace(id=11)]
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 7
    interaction.user.roles = []

    await modal.on_submit(interaction)

    kwargs = interaction.followup.send.call_args.kwargs
    description = kwargs["embed"].description
    assert "<@11>" in description
    assert "<@99>" not in description
    assert kwargs["view"] is not None
    db.log.assert_awaited_once()
