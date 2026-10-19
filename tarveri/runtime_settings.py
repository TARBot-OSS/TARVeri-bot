from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSetting:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    is_int: bool


RUNTIME_SETTINGS: tuple[RuntimeSetting, ...] = (
    RuntimeSetting("mass_join_window_seconds", "Mass-join window (seconds)", 60, 10, 3600, True),
    RuntimeSetting("mass_join_threshold", "Mass-join alert threshold (joins)", 20, 2, 10000, True),
    RuntimeSetting(
        "mass_join_cooldown_seconds", "Mass-join alert cooldown (seconds)", 600, 60, 86400, True
    ),
    RuntimeSetting("audit_flush_batch_size", "Audit batch size (rows)", 50, 1, 1000, True),
    RuntimeSetting(
        "audit_flush_interval_seconds", "Audit flush interval (seconds)", 2.0, 0.5, 60.0, False
    ),
)

SETTINGS_BY_KEY: dict[str, RuntimeSetting] = {s.key: s for s in RUNTIME_SETTINGS}


def default_runtime_values() -> dict[str, float | int]:
    return {s.key: _coerce(s, s.default) for s in RUNTIME_SETTINGS}


def parse_runtime_value(setting: RuntimeSetting, raw: str) -> float | int:
    text = raw.strip()
    try:
        value: float | int = int(text) if setting.is_int else float(text)
    except ValueError as exc:
        kind = "a whole number" if setting.is_int else "a number"
        raise ValueError(f"{setting.label} must be {kind}.") from exc
    if not setting.minimum <= value <= setting.maximum:
        raise ValueError(
            f"{setting.label} must be between {setting.minimum:g} and {setting.maximum:g}."
        )
    return value


def parse_runtime_form(raw_values: dict[str, str]) -> tuple[dict[str, float | int], list[str]]:
    values: dict[str, float | int] = {}
    errors: list[str] = []
    for setting in RUNTIME_SETTINGS:
        try:
            values[setting.key] = parse_runtime_value(setting, raw_values[setting.key])
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        return {}, errors
    return values, errors


def _coerce(setting: RuntimeSetting, value: float) -> float | int:
    return int(value) if setting.is_int else float(value)
