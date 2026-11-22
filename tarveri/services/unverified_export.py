"""Lists a server's members who have no verification record and packs them into a CSV for admins."""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Discord's default bot upload limit. Boosted servers allow more; callers pass guild.filesize_limit.
DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024
CSV_COLUMNS = [
    "discord_user_id",
    "username",
    "display_name",
    "joined_at",
    "days_in_server",
    "account_created",
    "is_guest",
    "roles",
]
# Cells starting with these run as formulas in Excel/Sheets (CSV injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class UnverifiedMember:
    discord_user_id: int
    username: str
    display_name: str
    joined_at: datetime | None
    account_created: datetime
    is_guest: bool
    roles: list[str]

    def days_in_server(self, now: datetime) -> int | None:
        return (now - self.joined_at).days if self.joined_at else None


def collect_unverified_members(
    members: Any, verified_ids: set[int], guest_role_id: int | None
) -> list[UnverifiedMember]:
    """Human members without a verification record, longest-waiting first."""
    result = []
    for m in members:
        if m.bot or m.id in verified_ids:
            continue
        roles = [r for r in m.roles if not r.is_default()]
        result.append(
            UnverifiedMember(
                discord_user_id=m.id,
                username=str(m),
                display_name=m.display_name,
                joined_at=m.joined_at,
                account_created=m.created_at,
                is_guest=guest_role_id is not None and any(r.id == guest_role_id for r in roles),
                roles=[r.name for r in roles],
            )
        )
    far_future = datetime.max.replace(tzinfo=UTC)
    result.sort(key=lambda u: u.joined_at or far_future)
    return result


def _safe_cell(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def build_unverified_csv(rows: list[UnverifiedMember], now: datetime | None = None) -> bytes:
    now = now or datetime.now(UTC)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for u in rows:
        days = u.days_in_server(now)
        writer.writerow(
            [
                str(u.discord_user_id),
                _safe_cell(u.username),
                _safe_cell(u.display_name),
                u.joined_at.isoformat() if u.joined_at else "",
                "" if days is None else days,
                u.account_created.isoformat(),
                "yes" if u.is_guest else "no",
                _safe_cell("; ".join(u.roles)),
            ]
        )
    # utf-8-sig so Excel shows non-Latin display names correctly.
    return buf.getvalue().encode("utf-8-sig")


def package_export(csv_bytes: bytes, base_name: str, limit: int = DEFAULT_UPLOAD_LIMIT) -> tuple[bytes, str] | None:
    """Returns (data, filename) that fits the upload limit: plain CSV, else zipped. None if even the zip is too big."""
    if len(csv_bytes) <= limit:
        return csv_bytes, f"{base_name}.csv"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(f"{base_name}.csv", csv_bytes)
    data = out.getvalue()
    return (data, f"{base_name}.zip") if len(data) <= limit else None
