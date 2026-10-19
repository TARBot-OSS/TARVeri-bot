---
name: tarveri
description: Working guide for the TARVeri Discord student/guest verification bot (tarveri/ package). Use when editing, testing, debugging or operating this repo: verification flow, guest tickets, roles, email OTP, self-healing, feature flags, tests and release rules.
---

# TARVeri working guide

TARVeri is a Discord bot for TARUMT. It assigns faculty, campus and study-level roles from a student ID, and runs a two-step review workflow for guests. Storage is SQLite (WAL) with Litestream replication. Deep reference: `.agents/skills/tarveri-verifier/SKILL.md` and `docs/`. Read the relevant section there before changing a subsystem.

## Where things live

| Concern | Location |
| --- | --- |
| Entry point | `tarveri_bot.py` -> `tarveri/bot.py` (`run_bot`, startup self-healing, persistent views) |
| Settings, ID parsing, faculty map, HMAC hashing | `tarveri/config.py` (`Settings.from_env`, `StudentIdInfo`) |
| DB facade | `tarveri/database.py`, composed from `tarveri/db/*_repo.py` mixins |
| Verification logic | `tarveri/services/verification_service.py` + `services/verification/*_mixin.py` (role, reconciliation, moderation, lifecycle) |
| Guest tickets, referrals | `services/guest_service.py`, `db/guest_repo.py`, `views/guest_views.py` |
| Email OTP, SMTP, bounce detection | `services/email_service.py` |
| Cards | `services/card_service.py`, `cogs/card_cog.py` |
| Slash commands | `tarveri/cogs/*` (`verification_cog`, `guest_cog`, `admin_cog`, `admin_dashboard`, `card_cog`) |
| Background daemons | `graduation_watchdog_service`, `outage_service`, `log_service`, `dead_letter_service`, `update_checker`, `storage_guard_service`, `uptime_service`, `console_service` |
| Ops | `scripts/update.sh`, `scripts/install_service.sh`, `deploy/*.service`, `litestream.yml` |

Layering: cogs and views handle Discord I/O only. Rules live in services. Persistence lives in `db/` repos. Put new logic in the lowest layer that owns it.

## Domain facts to keep correct

- Student ID shape `YY[campus][level]XXXXX`, programme code is the 3 letters after the year (e.g. `24WMR12331` -> `WMR`). Campus letters: W KL, P Penang, A Perak, J Johor, C/K Pahang, S Sabah. Level letters: D Diploma, R Degree, F Foundation, P Postgraduate.
- Verified students get four roles: base verified, faculty, campus, study level. Alumni get `TARUMT Alumni`.
- CPUS is a faculty; Foundation is a study level. Their reconciliation groups must never mix.
- Organizational roles (SRC, Council, Exco, Committee, Staff, Rep) must never match as faculty roles or be deduplicated.
- Duplicate-role cleanup deletes only roles the bot created (`bot_created_roles` plus audit log). Never delete admin-created roles.
- Past-verified users (`is_past_verified`) bypass email gating on re-verification and role restore. Removing this exemption caused incident INC-2026-09A (89 members stripped).
- Any batch action affecting >= `TARVERI_MASS_REVOCATION_THRESHOLD` (default 5) users must go through the mass-action approval view, not execute directly.
- Dates are relative to `datetime.now().year`. Do not hardcode years.
- Student emails are Fernet-encrypted at rest with an HMAC blind index for duplicate checks. Never log or store plaintext emails.
- Ticket codes use `format_ticket_seq()`: 1 -> `#A0001`, 10000 -> `#B0001`.
- Self-healing runs at startup and in `/admin diagnose`. New repair logic belongs in the reconciliation mixin so both paths pick it up.

## Config

Global flags are `TARVERI_*` env vars mapped onto `Settings` fields (see `.env.example` and the flag matrix in the agent skill). Per-guild settings live in `guild_settings` through `settings_repo`. A new flag needs: a `Settings` field, env parsing in `from_env`, an `.env.example` entry, and a test.

## Dev workflow

```bash
.venv/bin/pytest -v      # full suite, warnings are errors
ruff check .             # CI runs this too
python tarveri_bot.py    # run the bot (needs .env)
```

- `pytest.ini` sets `filterwarnings = error`. Mock guilds and members in tests must set `guild.roles = []` and `member.roles = []` to avoid unawaited `_aget` coroutine warnings.
- Schema changes need a backward-compatible migration in the `db/` layer (add column, backfill legacy rows), as done for `campus_code`, `level_code`, `programme_code`.
- Add a test in the matching `tests/test_*.py` for each behavior change. Run the narrowest test file first, then the full suite before finishing.
- Commit style: Conventional Commits (`feat(console): ...`, `fix(console): ...`).

## Release rules

Tag only major or minor feature releases (`v2.4.0`). Never tag patch fixes. For a large architecture-changing merge, tag the baseline on `main` before the merge and the new version after.

## Do not touch without being asked

`tarveri.db`, `backups/`, `logs/`, `.env`. They are live runtime data or secrets.
