"""Schema migrations: connect() must bring any earlier database to the current schema."""

import sqlite3

import pytest

from tarveri.database import Database

# The oldest layout the migrations still have to upgrade: no status columns and none of the
# campus, programme, expiry or email columns added later.
OLDEST_SQL = """
CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, welcome_channel_id INTEGER, updated_at TEXT);
CREATE TABLE referral_codes (
    code TEXT PRIMARY KEY, guild_id INTEGER NOT NULL, referrer_discord_id INTEGER NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE guest_tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
    applicant_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE verifications (
    discord_user_id INTEGER PRIMARY KEY, student_id_hash TEXT UNIQUE NOT NULL,
    faculty_code TEXT NOT NULL, verified_at TEXT NOT NULL, programme_code TEXT
);
INSERT INTO verifications VALUES (1, 'h1', 'FCI', '2024-03-01 10:00:00', NULL);
INSERT INTO verifications VALUES (2, 'h2', 'FOCS', '2025-01-15T09:00:00', NULL);
"""


# SQLite cannot add a NOT NULL column with ALTER TABLE, so a database upgraded from before this
# column existed keeps it nullable. Fresh databases get NOT NULL. Accepted; do not rebuild tables for it.
UPGRADE_NULLABLE_DRIFT = {("guild_settings", "updated_at")}


def _table_shape(path: str) -> dict[str, set[tuple]]:
    """Each table's columns as an unordered set, so a column added later does not count as a difference."""
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        shape = {}
        for name in names:
            cols = set()
            for r in con.execute(f"PRAGMA table_info({name})"):
                notnull = 0 if (name, r[1]) in UPGRADE_NULLABLE_DRIFT else r[3]
                cols.add((r[1], r[2], notnull, r[4], r[5]))
            shape[name] = cols
        return shape
    finally:
        con.close()


def _index_names(path: str) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        con.close()


@pytest.mark.asyncio
async def test_oldest_database_layout_upgrades(tmp_path):
    """Indexes on columns that the oldest layout lacks must not run before those columns are added."""
    path = str(tmp_path / "oldest.db")
    seed = sqlite3.connect(path)
    seed.executescript(OLDEST_SQL)
    seed.close()

    db = Database(path)
    await db.connect()
    await db.close()

    assert "idx_referral_status" in _index_names(path)


@pytest.mark.asyncio
async def test_upgraded_database_matches_fresh_schema(tmp_path):
    fresh_path = str(tmp_path / "fresh.db")
    fresh = Database(fresh_path)
    await fresh.connect()
    await fresh.close()

    upgraded_path = str(tmp_path / "upgraded.db")
    seed = sqlite3.connect(upgraded_path)
    seed.executescript(OLDEST_SQL)
    seed.close()
    upgraded = Database(upgraded_path)
    await upgraded.connect()
    await upgraded.close()

    assert _table_shape(upgraded_path) == _table_shape(fresh_path)
    assert _index_names(upgraded_path) == _index_names(fresh_path)


@pytest.mark.asyncio
async def test_legacy_rows_are_backfilled(tmp_path):
    path = str(tmp_path / "legacy.db")
    seed = sqlite3.connect(path)
    seed.executescript(OLDEST_SQL)
    seed.close()

    db = Database(path)
    await db.connect()
    await db.close()

    con = sqlite3.connect(path)
    rows = con.execute(
        "SELECT discord_user_id, campus_code, programme_code, card_expiry_date, is_alumni "
        "FROM verifications ORDER BY discord_user_id"
    ).fetchall()
    con.close()
    assert rows == [
        (1, "W", "WFCIR", "2027-10-31", 0),
        (2, "W", "WFOCSR", "2028-10-31", 0),
    ]


@pytest.mark.asyncio
async def test_connect_is_repeatable_after_close(tmp_path):
    path = str(tmp_path / "repeat.db")
    db = Database(path)
    await db.connect()
    await db.close()
    before = _table_shape(path)

    await db.connect()
    await db.close()

    assert _table_shape(path) == before
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    con.close()
