"""
Interactive Console CLI Service for TARVeri (Minecraft-style Terminal Backend).

Allows server administrators and bot hosters to execute administrative commands,
trigger verifications, inspect members, generate database snapshots, and monitor
system health directly from the terminal or tmux prompt with full scrollback support.
The TUI, PAM login and session handling live in the shared `tarbot_console` package.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import discord
from prompt_toolkit.completion import Completer, Completion
from tarbot_console import ConsoleCore

from tarveri.config import hash_student_id, parse_student_id

if TYPE_CHECKING:
    from tarveri.bot import TARVeriBot
    from tarveri.config import Settings
    from tarveri.database import Database
    from tarveri.services.verification_service import VerificationService

logger = logging.getLogger("tarveri.console")


FACULTY_CODES = [
    "FOCS",
    "FAFB",
    "FOET",
    "FOAS",
    "FOBE",
    "FCCI",
    "FSSH",
    "CPUS",
]

HELP_LINES = [
    "======================= TARVeri Console Commands =======================",
    "  help, ?                         Show this interactive help reference",
    "  login <username>                Authenticate via Linux PAM to unlock console",
    "  setup-admin <username>          Initialize the first console administrator",
    "  lock, logout                    Lock console session",
    "  user <list|add|remove> [name]   Manage authorized console administrators",
    "  view [split|logs|output]        Switch UI layout view (F2/F3 shortcuts)",
    "  minimize [output|logs]          Minimize terminal output or logs pane",
    "  restore [all|output|logs]       Restore minimized panes to split view",
    "  status                          View bot latency, uptime, guilds, memory",
    "  guilds                          List all connected Discord servers",
    "  stats [overview|faculties]      Show verification metrics and faculty counts",
    "  lookup <id_or_student_id>       Inspect member verification profile",
    "  verify <student_id> <user_id>   Force-verify a user directly",
    "  unverify <user_id> [reason]     Revoke verification and strip roles",
    "  backup [subfolder]              Trigger immediate SQLite snapshot backup",
    "  say <guild_id> <chan_id> <msg>  Send message to a channel as TARVeri",
    "  broadcast <message>             Send announcement to all configured channels",
    "  eval <code>                     Execute Python expression/statement",
    "  clear [output|logs|all]         Clear terminal screen or logs",
    "  stop, exit, quit                Gracefully shut down TARVeri",
    "  • Hotkeys: F2/Ctrl+O (Toggle Output), F3 (Toggle Logs), PgUp/PgDn (Scroll)",
    "========================================================================",
]


class _ArgumentCompleter(Completer):
    """Offers the words `rule` returns for an argument slot, else defers to the core completer."""

    def __init__(self, base: Completer, rule: Callable[[list[str]], list[str] | None]) -> None:
        self.base = base
        self.rule = rule

    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor(WORD=True)
        head = document.text_before_cursor[: len(document.text_before_cursor) - len(word)].split()
        options = self.rule(head)
        if options is None:
            yield from self.base.get_completions(document, complete_event)
            return
        for option in options:
            if option.lower().startswith(word.lower()):
                yield Completion(option, start_position=-len(word))


def _verify_argument_options(head: list[str]) -> list[str] | None:
    # `verify <student_id> <faculty-slot>`: the original readline completer offered faculty here.
    if len(head) == 2 and head[0] == "verify":
        return FACULTY_CODES
    return None


class ConsoleService(ConsoleCore):
    """Provides an interactive Split-Screen TUI for TARVeri with upper logs and compact bottom prompt."""

    bot_name = "TARVeri"
    history_file = "logs/.tarveri_history"
    help_lines = HELP_LINES
    alert_channel_names = frozenset({"tarveri-log", "tarveri_log", "tarveri-logs", "tarveri_logs"})
    extra_completions = {
        "status": None,
        "guilds": None,
        "stats": {"overview": None, "faculties": None},
        "lookup": None,
        "verify": None,
        "unverify": None,
        "backup": {"snapshot": None, "manual": None},
        "broadcast": None,
    }

    def __init__(
        self,
        bot: TARVeriBot,
        db: Database,
        service: VerificationService,
        settings: Settings,
    ) -> None:
        self.service = service
        super().__init__(bot, db, settings)

    def _get_completer(self) -> Completer | None:
        base = super()._get_completer()
        return _ArgumentCompleter(base, _verify_argument_options) if base is not None else None

    def eval_scope(self) -> dict[str, Any]:
        return {**super().eval_scope(), "service": self.service}

    async def dispatch_command(self, cmd: str, args: list[str]) -> bool:
        if cmd == "status":
            await self._cmd_status()
        elif cmd == "guilds":
            await self._cmd_guilds()
        elif cmd == "stats":
            await self._cmd_stats()
        elif cmd == "lookup":
            await self._cmd_lookup(args)
        elif cmd == "verify":
            await self._cmd_verify(args)
        elif cmd == "unverify":
            await self._cmd_unverify(args)
        elif cmd == "backup":
            await self._cmd_backup(args)
        elif cmd == "broadcast":
            await self._cmd_broadcast(args)
        else:
            return False
        return True

    async def _alert_before(self, embed: discord.Embed) -> None:
        hoster_id = getattr(self.settings, "hoster_discord_id", None)
        if not hoster_id:
            return
        hoster = self.bot.get_user(hoster_id)
        if not hoster:
            try:
                hoster = await self.bot.fetch_user(hoster_id)
            except Exception:
                hoster = None
        if hoster:
            try:
                await hoster.send(embed=embed)
            except Exception as exc:
                self.log.debug("Could not send DM to hoster: %s", exc)

    async def _alert_guild_primary(self, guild: discord.Guild, embed: discord.Embed) -> bool:
        # VerificationService targets or provisions #tarveri-log
        verif_service = self.service or getattr(self.bot, "service", None)
        if verif_service and hasattr(verif_service, "send_admin_security_alert"):
            try:
                return bool(await verif_service.send_admin_security_alert(guild, embed))
            except Exception as exc:
                self.log.debug("Failed sending security alert via send_admin_security_alert in %s: %s", guild.id, exc)
        return False

    async def _alert_guild_fallback(self, guild: discord.Guild, embed: discord.Embed) -> None:
        # Restricted admin review channel only. Never welcome_channel_id or system_channel (public chat).
        try:
            g_settings = await self.db.get_guild_settings(guild.id)
            review_chan_id = None
            if isinstance(g_settings, (tuple, list)) and len(g_settings) > 3:
                review_chan_id = g_settings[3]
            elif isinstance(g_settings, dict):
                review_chan_id = g_settings.get("review_channel_id")

            if review_chan_id:
                target_chan = guild.get_channel(review_chan_id)
                if target_chan and isinstance(target_chan, discord.TextChannel):
                    bot_member = getattr(guild, "me", None)
                    perms = target_chan.permissions_for(bot_member) if bot_member else None
                    if perms and perms.send_messages and perms.embed_links:
                        await target_chan.send(embed=embed)
        except Exception as exc:
            self.log.debug("Review channel fallback lookup error: %s", exc)

    async def _cmd_status(self) -> None:
        latency_ms = round(self.bot.latency * 1000, 1) if self.bot.latency else 0
        guilds_count = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)

        mem_mb = 0.0
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            mem_mb = round(usage / 1024, 2)
        except Exception as exc:
            self.log.debug("Resource usage retrieval skipped: %s", exc)

        uptime_str = "N/A"
        if hasattr(self.bot, "uptime_service") and self.bot.uptime_service:
            try:
                ups = self.bot.uptime_service
                if hasattr(ups, "current_uptime_str") and ups.current_uptime_str:
                    uptime_str = ups.current_uptime_str
                elif hasattr(ups, "current_uptime_seconds"):
                    sec = int(ups.current_uptime_seconds)
                    hours, rem = divmod(sec, 3600)
                    mins, secs = divmod(rem, 60)
                    uptime_str = f"{hours}h {mins}m {secs}s"
                elif hasattr(ups, "get_uptime_seconds"):
                    sec = int(ups.get_uptime_seconds())
                    hours, rem = divmod(sec, 3600)
                    mins, secs = divmod(rem, 60)
                    uptime_str = f"{hours}h {mins}m {secs}s"
            except Exception as exc:
                self.log.debug("Failed computing uptime string: %s", exc)

        usr_tag = str(self.bot.user) if self.bot.user else "N/A"
        usr_id = self.bot.user.id if self.bot.user else "N/A"
        out = (
            f"[STATUS] Bot User: {usr_tag} (ID: {usr_id})\n"
            f"[STATUS] WebSocket Ping: {latency_ms} ms | Memory: ~{mem_mb} MB\n"
            f"[STATUS] Connected Guilds: {guilds_count} | Total Members: {total_members}\n"
            f"[STATUS] Continuous Uptime: {uptime_str}\n"
            f"[STATUS] Database: {self.settings.db_path} (Connected: {self.db.is_connected})"
        )
        self.write_output(out)

    async def _cmd_guilds(self) -> None:
        if not self.bot.guilds:
            self.write_output("[INFO] No connected guilds.")
            return

        lines = [f"\n--- Connected Guilds ({len(self.bot.guilds)}) ---"]
        for g in self.bot.guilds:
            owner_tag = str(g.owner) if g.owner else "Unknown"
            lines.append(f"• [{g.id}] {g.name:<30} | Members: {g.member_count:<5} | Owner: {owner_tag}")
        lines.append("------------------------------------------------")
        self.write_output("\n".join(lines))

    async def _cmd_stats(self) -> None:
        try:
            total = await self.db.total_verified()
            alumni = await self.db.count_alumni()
            active_students = total - alumni
            faculty_counts = await self.db.counts_by_faculty()
            last_24h = await self.db.verified_in_last(24)

            lines = [
                "\n--- Verification Statistics ---",
                f"• Total Verified Records: {total}",
                f"• Active Students:        {active_students}",
                f"• Verified Alumni:        {alumni}",
                f"• Verified (Last 24h):    {last_24h}",
                "• Faculty Distribution:",
            ]
            for fac, count in faculty_counts:
                lines.append(f"    - {fac:<6}: {count}")
            lines.append("-------------------------------")
            self.write_output("\n".join(lines))
        except Exception as e:
            self.write_output(f"[ERROR] Failed to fetch stats: {e}")

    async def _cmd_lookup(self, args: list[str]) -> None:
        if not args:
            self.write_output("[WARN] Usage: lookup <discord_user_id | student_id>")
            return

        query = args[0].strip()
        details: dict[str, Any] | None = None
        user_id: int | None = None

        if query.isdigit() and len(query) >= 16:
            user_id = int(query)
            details = await self.db.get_verification_details(user_id)
        else:
            id_hash = hash_student_id(query, self.settings.id_hash_secret)
            res = await self.db.get_verification_by_id_hash(id_hash)
            if res:
                user_id = res[0]
                details = await self.db.get_verification_details(user_id)

        if not details or user_id is None:
            self.write_output(f"[INFO] No verification record found for query '{query}'.")
            return

        user_obj = self.bot.get_user(user_id)
        tag = str(user_obj) if user_obj else f"User {user_id}"

        lines = [
            f"\n--- Verification Profile: {tag} ---",
            f"• Discord User ID:  {user_id}",
            f"• Faculty:          {details.get('faculty_code')}",
            f"• Campus:           {details.get('campus_code', 'W')}",
            f"• Study Level:      {details.get('level_code', 'R')}",
            f"• Programme Code:   {details.get('programme_code', 'N/A')}",
            f"• Expiry Date:      {details.get('card_expiry_date', 'N/A')}",
            f"• Is Alumni:        {details.get('is_alumni', False)}",
            f"• Verified At:      {details.get('verified_at')}",
            "------------------------------------------",
        ]
        self.write_output("\n".join(lines))

    async def _cmd_verify(self, args: list[str]) -> None:
        if len(args) < 2:
            self.write_output("[WARN] Usage: verify <student_id> <discord_user_id>")
            return

        raw_student_id = args[0].strip()
        user_id_raw = args[1].strip()

        if not user_id_raw.isdigit():
            self.write_output(f"[ERROR] Invalid Discord user ID '{user_id_raw}'. Must be numeric.")
            return

        user_id = int(user_id_raw)
        parsed = parse_student_id(raw_student_id)
        if not parsed.is_valid:
            self.write_output(f"[ERROR] Invalid student ID '{raw_student_id}'. Format: 23WMD09867")
            return

        user = self.bot.get_user(user_id)
        if not user:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                user = None

        if not user:
            self.write_output(f"[ERROR] Could not resolve Discord user with ID {user_id}.")
            return

        self.write_output(f"[INFO] Verifying {user} with Student ID {parsed.student_id}...")
        res = await self.service.perform_verification(
            user=user,
            raw_student_id=parsed.student_id,
        )
        self.write_output(f"[RESULT] {res}")

    async def _cmd_unverify(self, args: list[str]) -> None:
        if not args:
            self.write_output("[WARN] Usage: unverify <discord_user_id> [reason]")
            return

        user_id_raw = args[0].strip()
        if not user_id_raw.isdigit():
            self.write_output(f"[ERROR] Invalid Discord user ID '{user_id_raw}'. Must be numeric.")
            return

        user_id = int(user_id_raw)
        reason = " ".join(args[1:]) if len(args) > 1 else "Unverified via host console"

        res = await self.service.unverify_member(
            user_id=user_id,
            admin=self.bot.user,
            current_guild=None,
            reason=reason,
        )
        if res.get("success"):
            g_count = res.get("guilds_updated", 0)
            self.write_output(f"[SUCCESS] User {user_id} unverified cleanly. Roles stripped across {g_count} guild(s).")
        else:
            self.write_output(f"[WARN] User {user_id} was not verified or could not be unverified.")

    async def _cmd_backup(self, args: list[str]) -> None:
        subfolder = args[0] if args else "daily"
        self.write_output(f"[INFO] Creating point-in-time database snapshot in backups/{subfolder}...")
        try:
            path = await self.db.create_backup(subfolder=subfolder)
            self.write_output(f"[SUCCESS] Database backup saved to: {path}")
        except Exception as e:
            self.write_output(f"[ERROR] Database backup failed: {e}")

    async def _cmd_broadcast(self, args: list[str]) -> None:
        if not args:
            self.write_output("[WARN] Usage: broadcast <message>")
            return

        msg = " ".join(args)
        sent = 0
        failed = 0
        for guild in self.bot.guilds:
            target_chan = None
            settings = await self.db.get_guild_settings(guild.id)
            if settings and settings.get("welcome_channel_id"):
                target_chan = guild.get_channel(settings["welcome_channel_id"])
            if not target_chan:
                target_chan = guild.system_channel
            if not target_chan:
                for c in guild.text_channels:
                    if c.permissions_for(guild.me).send_messages:
                        target_chan = c
                        break

            if target_chan and isinstance(target_chan, discord.TextChannel):
                try:
                    await target_chan.send(f"📢 **System Broadcast:** {msg}")
                    sent += 1
                except Exception:
                    failed += 1

        self.write_output(f"[SUCCESS] Broadcast dispatched to {sent} guild(s). ({failed} failed)")
