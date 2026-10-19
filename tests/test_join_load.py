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


async def test_mass_join_alert_fires_once_per_cooldown(db):
    service = MagicMock(spec=VerificationService)
    service.send_admin_security_alert = AsyncMock()
    cog = VerificationCog(MagicMock(), db, service, RateLimiter())
    cog._handle_member_join = AsyncMock()
    guild = MagicMock(id=987, name="Raid Test Guild")

    threshold = db.runtime_settings["mass_join_threshold"]
    for i in range(threshold + 5):
        await cog.on_member_join(MagicMock(id=i, guild=guild))

    assert service.send_admin_security_alert.await_count == 1
    assert cog._handle_member_join.await_count == threshold + 5


async def test_no_mass_join_alert_below_threshold(db):
    service = MagicMock(spec=VerificationService)
    service.send_admin_security_alert = AsyncMock()
    cog = VerificationCog(MagicMock(), db, service, RateLimiter())
    cog._handle_member_join = AsyncMock()
    guild = MagicMock(id=988, name="Quiet Guild")

    for i in range(db.runtime_settings["mass_join_threshold"] - 1):
        await cog.on_member_join(MagicMock(id=i, guild=guild))

    service.send_admin_security_alert.assert_not_awaited()


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
    batch_size = db.runtime_settings["audit_flush_batch_size"]
    for i in range(batch_size):
        await db.log("INFO", "BULK_EVENT", f"message {i}")

    async with db.transaction() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM audit_log WHERE event_type = 'BULK_EVENT'")
        assert (await cursor.fetchone())[0] == batch_size


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
