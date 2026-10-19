import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tarveri.cogs.verification_cog import MAX_CONCURRENT_JOIN_HANDLERS, VerificationCog
from tarveri.database import Database
from tarveri.rate_limiter import RateLimiter
from tarveri.services.verification_service import VerificationService


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "join_load.db"))
    await database.connect()
    yield database
    await database.close()


async def test_join_handlers_never_exceed_concurrency_cap(db):
    cog = VerificationCog(MagicMock(), db, MagicMock(spec=VerificationService), RateLimiter())
    in_flight = 0
    peak = 0

    async def tracked_handler(member):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1

    cog._handle_member_join = AsyncMock(side_effect=tracked_handler)
    members = [MagicMock(id=i) for i in range(60)]

    await asyncio.gather(*(cog.on_member_join(m) for m in members))

    assert cog._handle_member_join.await_count == 60
    assert peak == MAX_CONCURRENT_JOIN_HANDLERS


async def test_audit_rows_batch_until_flush(db):
    for i in range(3):
        await db.log("INFO", "TEST_EVENT", f"message {i}")

    async with db.transaction() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'TEST_EVENT'")
        assert (await cursor.fetchone())[0] == 0

    await db.flush_audit_log()

    async with db.transaction() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'TEST_EVENT'")
        assert (await cursor.fetchone())[0] == 3


async def test_audit_buffer_flushes_when_batch_size_reached(db):
    for i in range(Database.AUDIT_FLUSH_BATCH_SIZE):
        await db.log("INFO", "BULK_EVENT", f"message {i}")

    async with db.transaction() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'BULK_EVENT'")
        assert (await cursor.fetchone())[0] == Database.AUDIT_FLUSH_BATCH_SIZE


async def test_close_flushes_pending_audit_rows(tmp_path):
    path = str(tmp_path / "close_flush.db")
    database = Database(path)
    await database.connect()
    await database.log("WARNING", "SHUTDOWN_EVENT", "pending row")
    await database.close()

    reopened = Database(path)
    await reopened.connect()
    async with reopened.transaction() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'SHUTDOWN_EVENT'")
        assert (await cursor.fetchone())[0] == 1
    await reopened.close()
