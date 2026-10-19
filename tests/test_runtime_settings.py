from unittest.mock import AsyncMock, MagicMock

import pytest

from tarveri.cogs.verification_cog import VerificationCog
from tarveri.database import Database
from tarveri.rate_limiter import RateLimiter
from tarveri.runtime_settings import (
    RUNTIME_SETTINGS,
    SETTINGS_BY_KEY,
    parse_runtime_form,
    parse_runtime_value,
)
from tarveri.services.verification_service import VerificationService


def _valid_form() -> dict[str, str]:
    return {s.key: f"{s.default:g}" for s in RUNTIME_SETTINGS}


def test_whole_number_setting_rejects_decimals_and_out_of_range():
    threshold = SETTINGS_BY_KEY["mass_join_threshold"]

    assert parse_runtime_value(threshold, " 25 ") == 25
    with pytest.raises(ValueError, match="whole number"):
        parse_runtime_value(threshold, "2.5")
    with pytest.raises(ValueError, match="between"):
        parse_runtime_value(threshold, "1")
    with pytest.raises(ValueError, match="whole number"):
        parse_runtime_value(threshold, "many")


def test_form_reports_every_invalid_field_and_saves_nothing():
    form = _valid_form()
    form["mass_join_threshold"] = "0"
    form["audit_flush_interval_seconds"] = "abc"

    values, errors = parse_runtime_form(form)

    assert len(errors) == 2
    assert values == {}


def test_valid_form_returns_typed_values():
    values, errors = parse_runtime_form(_valid_form())

    assert errors == []
    assert values["mass_join_window_seconds"] == 60
    assert isinstance(values["audit_flush_interval_seconds"], float)


async def test_saved_settings_survive_restart(tmp_path):
    path = str(tmp_path / "runtime.db")
    first = Database(path)
    await first.connect()
    await first.set_runtime_setting("mass_join_threshold", 33, updated_by=1)
    await first.close()

    second = Database(path)
    await second.connect()
    assert second.runtime_settings["mass_join_threshold"] == 33
    assert second.runtime_settings["mass_join_window_seconds"] == 60
    await second.close()


async def test_corrupt_stored_value_falls_back_to_default(tmp_path):
    path = str(tmp_path / "corrupt.db")
    database = Database(path)
    await database.connect()
    await database._conn.execute(
        "INSERT INTO runtime_settings (key, value) VALUES ('mass_join_threshold', 'lots');"
    )
    await database._conn.commit()
    await database.load_runtime_settings()

    assert database.runtime_settings["mass_join_threshold"] == 20
    await database.close()


async def test_unknown_setting_key_is_rejected(tmp_path):
    database = Database(str(tmp_path / "unknown.db"))
    await database.connect()

    with pytest.raises(KeyError):
        await database.set_runtime_setting("not_a_setting", 1, updated_by=1)
    await database.close()


async def test_changed_threshold_applies_to_next_joins(tmp_path):
    database = Database(str(tmp_path / "live.db"))
    await database.connect()
    await database.set_runtime_setting("mass_join_threshold", 3, updated_by=1)

    service = MagicMock(spec=VerificationService)
    service.send_admin_security_alert = AsyncMock()
    cog = VerificationCog(MagicMock(), database, service, RateLimiter())
    cog._handle_member_join = AsyncMock()
    guild = MagicMock(id=555, name="Live Tune Guild")

    for i in range(3):
        await cog.on_member_join(MagicMock(id=i, guild=guild))

    assert service.send_admin_security_alert.await_count == 1
    await database.close()
