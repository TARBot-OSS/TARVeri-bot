"""What TARClub relies on from TARVeri: schema version, verifications columns and student roles.

The expected values live in tarbot_console.contracts, which TARClub reads too.
"""

import sqlite3

import pytest
from tarbot_console.contracts import (
    TARVERI_SCHEMA_VERSION,
    TARVERI_STUDENT_ROLE_NAMES,
    TARVERI_VERIFICATION_COLUMNS,
)

from tarveri.config import FACULTY_ROLE_NAMES, STUDY_LEVEL_ROLE_NAMES
from tarveri.database import SCHEMA_VERSION, Database


@pytest.mark.asyncio
async def test_schema_version_matches_contract(tmp_path):
    path = str(tmp_path / "contract.db")
    db = Database(path)
    await db.connect()
    await db.close()

    con = sqlite3.connect(path)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
    assert SCHEMA_VERSION == TARVERI_SCHEMA_VERSION
    assert version == TARVERI_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_verifications_table_has_every_column_tarclub_reads(tmp_path):
    path = str(tmp_path / "columns.db")
    db = Database(path)
    await db.connect()
    await db.close()

    con = sqlite3.connect(path)
    try:
        columns = {row[1] for row in con.execute("PRAGMA table_info(verifications)")}
    finally:
        con.close()
    assert TARVERI_VERIFICATION_COLUMNS <= columns


def test_every_role_tarveri_assigns_is_a_student_role_for_tarclub():
    assigned = {name.lower() for name in FACULTY_ROLE_NAMES | STUDY_LEVEL_ROLE_NAMES}
    assert assigned <= TARVERI_STUDENT_ROLE_NAMES
