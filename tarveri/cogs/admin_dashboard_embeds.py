"""Embed builders for the admin dashboard view."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

import discord

from tarveri.config import (
    FACULTY_ROLES,
    SRC_ROLE_NAMES,
    resolve_campus_role,
    resolve_faculty_role,
    resolve_study_level_role,
)
from tarveri.services.log_service import (
    list_daily_logs,
    list_log_archives,
)
from tarveri.services.update_checker import UpdateCheckerService
from tarveri.services.uptime_service import format_duration_seconds
from tarveri.utils import format_ticket_seq

if TYPE_CHECKING:
    pass

logger = logging.getLogger("tarveri")


class DashboardEmbedsMixin:
    """Builds the dashboard's embeds. Combined into AdminDashboardView."""

    async def build_current_embed(self, guild: discord.Guild | None) -> discord.Embed:
        if self.current_category == "overview":
            return await self.build_overview_embed(guild)
        elif self.current_category == "config":
            return await self.build_config_embed(guild)
        elif self.current_category == "diagnose":
            return await self.build_diagnose_embed(guild)
        elif self.current_category == "moderation":
            return await self.build_moderation_embed(guild)
        elif self.current_category == "tickets":
            return await self.build_tickets_embed(guild)
        elif self.current_category == "backup":
            return await self.build_backup_embed(guild)
        elif self.current_category == "logs":
            return await self.build_logs_embed(guild)
        elif self.current_category == "panel":
            return await self.build_panel_embed(guild)
        elif self.current_category == "updates":
            return await self.build_updates_embed(guild)
        elif self.current_category == "randomtag":
            return await self.build_randomtag_embed(guild)
        elif self.current_category == "uptime":
            return await self.build_uptime_embed(guild)
        return await self.build_overview_embed(guild)

    # --- Embed Builders ---

    async def build_overview_embed(self, guild: discord.Guild | None) -> discord.Embed:
        total = await self.cog.db.total_verified()
        total_alumni = await self.cog.db.count_alumni()
        faculty_counts = await self.cog.db.counts_by_faculty()
        last_24h = await self.cog.db.verified_in_last(24)
        last_7d = await self.cog.db.verified_in_last(24 * 7)

        embed = discord.Embed(
            title="🛡️ TARVeri — Administrator Control Center",
            description="Welcome to the unified server management and moderation dashboard.",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Total Verified Students", value=f"**{total}** students", inline=True)
        embed.add_field(name="Graduated Alumni", value=f"**{total_alumni}** alumni", inline=True)
        embed.add_field(name="Active Guilds", value=f"**{len(self.cog.bot.guilds)}** servers", inline=True)
        embed.add_field(name="Verified Past 24h", value=f"**{last_24h}** new", inline=True)
        embed.add_field(name="Verified Past 7d", value=f"**{last_7d}** new", inline=True)

        email_stats = await self.cog.db.get_email_verification_stats(guild.id if guild else None)
        email_status_text = (
            f"**{email_stats['email_verified_students']}** / **{total}** ({email_stats['email_verified_rate']}%)"
        )
        embed.add_field(name="📧 Email Verified Students", value=email_status_text, inline=True)
        if guild:
            opt_status = (
                "🔒 **Mandatory (Opted In)**"
                if email_stats["guild_opted_in"]
                else "⚪ **Optional (Default: Opted Out)**"
            )
            embed.add_field(name="📧 Server Email Policy", value=opt_status, inline=True)

        uptime_service = getattr(self.cog, "uptime_service", None) or getattr(self.cog.bot, "uptime_service", None)
        if uptime_service and hasattr(uptime_service, "get_sla_metrics"):
            res = uptime_service.get_sla_metrics()
            sla_metrics = await res if inspect.isawaitable(res) else res
            if isinstance(sla_metrics, dict) and "sla_24h" in sla_metrics and isinstance(sla_metrics["sla_24h"], dict):
                sla_24h_val = sla_metrics["sla_24h"].get("sla_percent", 100.0)
                tot_up = sla_metrics.get("total_uptime_str")
                total_text = f" (Total: **{tot_up}**)" if tot_up else ""
                embed.add_field(
                    name="⏱️ Uptime & 24h SLA",
                    value=f"**{sla_metrics.get('current_uptime_str', 'Online')}**{total_text} • **{sla_24h_val:.2f}%** ({sla_metrics['sla_24h'].get('grade', 'Healthy')})",
                    inline=True,
                )

        if faculty_counts:
            breakdown_lines = []
            for f_code, count in faculty_counts:
                faculty_name = resolve_faculty_role(f_code) or FACULTY_ROLES.get(f_code, f"Code {f_code}")
                percentage = (count / total * 100) if total > 0 else 0
                breakdown_lines.append(f"• **{faculty_name}** (`{f_code}`): {count} ({percentage:.1f}%)")
            embed.add_field(name="Faculty Distribution", value="\n".join(breakdown_lines), inline=False)
        else:
            embed.add_field(name="Faculty Distribution", value="No student verifications recorded yet.", inline=False)

        embed.set_footer(text="Use the dropdown menu below to navigate categories.")
        return embed

    async def build_config_embed(self, guild: discord.Guild | None) -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ Server Channel & Role Configuration",
            description=f"Current settings for **{guild.name if guild else 'Server'}**:",
            color=discord.Color.dark_teal(),
        )
        if not guild:
            embed.description = "Configuration requires a Discord server context."
            return embed

        settings = await self.cog.db.get_guild_settings(guild.id)
        w_id = settings[0] if settings else None
        h_id = settings[1] if settings else None
        g_role = settings[2] if settings and len(settings) > 2 and settings[2] else "Guest"
        r_id = settings[3] if settings and len(settings) > 3 else None
        adm_role = (
            settings[4]
            if settings and len(settings) > 4 and settings[4]
            else f"Auto-detect ({self.cog.admin_role_name})"
        )
        is_email_opted_in = bool(settings[5]) if settings and len(settings) > 5 else False
        is_email_enforced = bool(settings[6]) if settings and len(settings) > 6 else False

        w_ch = guild.get_channel(w_id) if w_id else None
        h_ch = guild.get_channel(h_id) if h_id else None
        r_ch = guild.get_channel(r_id) if r_id else None

        embed.add_field(
            name="📢 Welcome Channel",
            value=w_ch.mention if w_ch else (f"`ID: {w_id}`" if w_id else "*Auto-detect (#welcome / #verify)*"),
            inline=True,
        )
        embed.add_field(
            name="❓ Help Channel",
            value=h_ch.mention if h_ch else (f"`ID: {h_id}`" if h_id else "*Auto-detect (#help / #support)*"),
            inline=True,
        )
        embed.add_field(
            name="🎫 Guest Review Channel",
            value=r_ch.mention if r_ch else (f"`ID: {r_id}`" if r_id else "*Auto-detect (#tickets / #reviews)*"),
            inline=True,
        )
        embed.add_field(name="👥 Guest Role Name", value=f"`{g_role}`", inline=True)
        embed.add_field(name="🛡️ Admin / Reviewer Role", value=f"`{adm_role}`", inline=True)
        email_mode_str = "🔒 **Mandatory (Opted In)**" if is_email_opted_in else "⚪ **Optional (Default: Opted Out)**"
        embed.add_field(name="📧 Email Verification Policy", value=email_mode_str, inline=True)
        enforce_mode_str = (
            "🔴 **Enforced (Retroactive Stripping)**"
            if is_email_enforced
            else "🟢 **Disabled (Existing Roles Preserved)**"
        )
        embed.add_field(name="🛡️ Email Role Enforcement", value=enforce_mode_str, inline=True)

        is_src_enabled = bool(settings[7]) if settings and len(settings) > 7 else False
        src_mode_str = "🟢 **Enabled (Auto-managed)**" if is_src_enabled else "⚪ **Disabled (Opted Out)**"
        embed.add_field(name="🏛️ Faculty SRC Roles", value=src_mode_str, inline=True)

        embed.set_footer(text="Use the buttons below to modify channels, roles, or reset to defaults.")
        return embed

    async def build_diagnose_embed(self, guild: discord.Guild | None) -> discord.Embed:
        if not guild:
            return discord.Embed(
                title="🩺 Diagnostics", description="Must be run inside a Discord server.", color=discord.Color.red()
            )

        warnings = self.cog.service.diagnose_guild_permissions(guild)
        embed = discord.Embed(
            title=f"🩺 Server Health & Self-Healing Diagnostics — {guild.name}",
            color=discord.Color.green() if not warnings else discord.Color.orange(),
        )

        if warnings:
            embed.add_field(
                name="⚠️ Permission / Hierarchy Issues Detected",
                value="\n".join(f"• {w}" for w in warnings),
                inline=False,
            )
        else:
            embed.add_field(
                name="✅ Permissions & Role Hierarchy",
                value="All required bot permissions and role positions are healthy.",
                inline=False,
            )

        is_src_enabled = await self.cog.db.is_guild_src_roles_enabled(guild.id)
        existing_src_count = sum(1 for r in getattr(guild, "roles", []) if getattr(r, "name", "") in SRC_ROLE_NAMES)
        src_status_str = (
            f"🟢 **Enabled** ({existing_src_count}/{len(SRC_ROLE_NAMES)} present • Auto-managed)"
            if is_src_enabled
            else f"⚪ **Disabled** ({existing_src_count} present • Skipped for this server)"
        )

        embed.add_field(
            name="🔄 Self-Healing Capabilities",
            value=(
                f"• **SRC Roles**: {src_status_str}\n"
                "• **Role Deduplication**: Migrates members and cleans bot duplicates.\n"
                "• **Member Role Reconciliation**: Restores faculty/alumni roles to verified students."
            ),
            inline=False,
        )
        embed.set_footer(text="Use buttons below to run diagnostics, toggle SRC roles, or remove them.")
        return embed

    async def build_moderation_embed(self, guild: discord.Guild | None) -> discord.Embed:
        total = await self.cog.db.total_verified()
        total_alumni = await self.cog.db.count_alumni()

        embed = discord.Embed(
            title="👥 Member Moderation & Verification Actions",
            description=(
                f"Currently managing **{total}** verified student(s) and **{total_alumni}** graduated alumni.\n\n"
                "Choose a moderation action below to open the corresponding input form:"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="🔍 Lookup Member Info",
            value="Inspect student ID status, institutional email OTP status, faculty/campus/level roles, join date, graduation year, academic transitions, guest tickets, and audit history.",
            inline=False,
        )
        embed.add_field(
            name="❌ Unverify Student",
            value="Unlinks student ID hash, resets rate limiting, and revokes faculty roles across mutual servers.",
            inline=False,
        )
        embed.add_field(
            name="🎓 Revoke Alumni Status",
            value="Revokes alumni graduation claim and removes `TARUMT Alumni` role across mutual servers.",
            inline=False,
        )
        return embed

    async def build_tickets_embed(self, guild: discord.Guild | None, status_filter: str | None = None) -> discord.Embed:
        if not guild:
            return discord.Embed(
                title="🎟️ Guest Review Tickets", description="Must be run in a server.", color=discord.Color.red()
            )

        tickets = await self.cog.db.list_guest_tickets(guild.id, status=status_filter, limit=6)
        embed = discord.Embed(
            title=f"🎟️ Recent Guest Review Tickets — {guild.name}",
            color=discord.Color.dark_teal(),
        )
        if not tickets:
            embed.description = (
                f"No guest review tickets found{' with status ' + status_filter if status_filter else ''}."
            )
            return embed

        embed.description = f"Showing **{len(tickets)}** recent ticket(s):"
        for t in tickets:
            seq = t.get("ticket_seq") or t.get("ticket_id")
            seq_code = format_ticket_seq(seq)
            t_status = t.get("status", "OPEN")
            status_emoji = {
                "OPEN": "⏳",
                "APPROVED": "✅",
                "REJECTED": "🛑",
                "CLOSED": "🔒",
                "DISMISSED": "📁",
                "CANCELLED": "⚪",
                "EXPIRED": "⏰",
                "LEFT_SERVER": "🚪",
                "BANNED": "🔨",
            }.get(t_status, "📄")

            thread_mention = f"<#{t['channel_id']}>"
            applicant_mention = f"<@{t['applicant_id']}>"
            reason_info = f'\n> *"{t["close_reason"]}"*' if t.get("close_reason") else ""

            embed.add_field(
                name=f"{status_emoji} Ticket #{seq_code} — {t_status}",
                value=f"**Applicant:** {applicant_mention} | **Thread:** {thread_mention}\n**Created:** `{t.get('created_at', 'N/A')}`{reason_info}",
                inline=False,
            )
        return embed

    async def build_backup_embed(self, guild: discord.Guild | None) -> discord.Embed:
        settings = getattr(self.cog.bot, "settings", None)
        backup_dir = (
            settings.backup_dir if settings and isinstance(getattr(settings, "backup_dir", None), str) else "backups"
        )
        max_backups = (
            settings.max_backups if settings and isinstance(getattr(settings, "max_backups", None), int) else 10
        )
        backups = self.cog.db.list_backups(backup_dir=backup_dir)
        embed = discord.Embed(
            title="💾 Database Backups & Snapshot Snapshots",
            description=f"Backups are stored in `{backup_dir}` and rotated up to **{max_backups}** files.",
            color=discord.Color.green() if backups else discord.Color.blue(),
        )
        if backups:
            lines = []
            for b in backups[:7]:
                size_kb = b.get("size_bytes", 0) / 1024 if "size_bytes" in b else b.get("size_kb", 0)
                time_str = b.get("timestamp") or b.get("created_at") or "N/A"
                lines.append(f"• 📦 `{b['filename']}` — {size_kb:.1f} KB (`{time_str}`)")
            embed.add_field(name=f"Available Snapshots ({len(backups)} total)", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Available Snapshots", value="No snapshots found in backup directory.", inline=False)
        return embed

    async def build_logs_embed(self, guild: discord.Guild | None) -> discord.Embed:
        settings = getattr(self.cog.bot, "settings", None)
        logs_dir = settings.logs_dir if settings and isinstance(getattr(settings, "logs_dir", None), str) else "logs"
        tz_name = (
            settings.timezone_name
            if settings and isinstance(getattr(settings, "timezone_name", None), str)
            else "Asia/Kuala_Lumpur"
        )

        daily_logs = list_daily_logs(logs_dir=logs_dir, tz_name=tz_name)
        archives = list_log_archives(logs_dir=logs_dir)

        embed = discord.Embed(
            title=f"📋 TARVeri Log Management & Historical Archives (`{logs_dir}/`)",
            color=discord.Color.blue(),
        )
        if daily_logs:
            daily_desc = [
                f"• 📄 `{dl['filename']}` — {dl['size_bytes'] / 1024:.1f} KB ({dl['lines']} lines)"
                for dl in daily_logs[:5]
            ]
            embed.add_field(
                name=f"Active Daily Logs ({len(daily_logs)} total)", value="\n".join(daily_desc), inline=False
            )
        else:
            embed.add_field(name="Active Daily Logs", value="No daily log files found.", inline=False)

        if archives:
            archive_desc = [
                f"• 📦 `{ar['filename']}` — {ar['size_bytes'] / 1024:.1f} KB ({ar['file_count']} logs bundled)"
                for ar in archives[:5]
            ]
            embed.add_field(
                name=f"10-Day Archives ({len(archives)} total)", value="\n".join(archive_desc), inline=False
            )
        else:
            embed.add_field(
                name="10-Day Archives",
                value="No archives created yet (logs $>10$ days old are compressed).",
                inline=False,
            )

        return embed

    async def build_panel_embed(self, guild: discord.Guild | None) -> discord.Embed:
        embed = discord.Embed(
            title="🚀 Deploy Verification Gateway Panel",
            description=(
                "The **Verification Gateway Panel** is a permanent 3-button message that allows newcomers to easily:\n\n"
                "1. 🎓 **Verify TARUMT Student**: Submit student ID via modal.\n"
                "2. 🎟️ **Enter Referral Code**: Submit invite referral code.\n"
                "3. 🌐 **Apply as Guest**: Fill out guest application form.\n\n"
                "Click below to deploy it to the current channel or pick a specific channel."
            ),
            color=discord.Color.dark_teal(),
        )
        return embed

    async def build_updates_embed(self, guild: discord.Guild | None) -> discord.Embed:
        checker = self.cog.update_checker
        if not checker:
            checker = UpdateCheckerService(bot=self.cog.bot, db=self.cog.db, update_stream="auto")

        is_avail, count, local_h, remote_h, target_stream = await checker.check_for_updates()
        embed = discord.Embed(
            title="🔄 TARVeri Update Checker & Synchronization",
            color=discord.Color.green() if not is_avail else discord.Color.gold(),
        )
        embed.add_field(name="Target Stream", value=f"`{target_stream}`", inline=False)
        embed.add_field(name="Local Commit", value=f"`{local_h[:7]}`" if local_h else "*Unknown*", inline=True)
        embed.add_field(name="Remote Commit", value=f"`{remote_h[:7]}`" if remote_h else "*Unknown*", inline=True)

        if is_avail:
            branch_arg = target_stream.replace("origin/", "").strip()
            embed.description = (
                f"🔔 **Update available!** Remote is **{count} commit(s)** ahead.\n"
                f"To update, run `./scripts/update.sh {branch_arg}` on your host terminal."
            )
        else:
            embed.description = "✅ TARVeri is running the latest version on this stream."

        return embed

    async def build_user_details_embed(self, user_id: int, guild: discord.Guild | None) -> discord.Embed:
        """Builds an exhaustive audit and profile embed for a specific Discord user."""
        target_user = self.cog.bot.get_user(user_id)
        target_member = guild.get_member(user_id) if guild else None

        user_avatar_url = (
            target_user.display_avatar.url
            if target_user
            else (target_member.display_avatar.url if target_member else None)
        )

        details = await self.cog.db.get_verification_details(user_id)

        embed = discord.Embed(
            title="🔍 Member Verification & Audit Record",
            description=f"Showing full verification state and security profile for <@{user_id}> (`{user_id}`).",
            color=discord.Color.blue() if details else discord.Color.greyple(),
        )
        if user_avatar_url:
            embed.set_thumbnail(url=user_avatar_url)

        # 1. Verification & Identity Status
        if details:
            fac_code = details.get("faculty_code") or "N/A"
            fac_name = FACULTY_ROLES.get(fac_code, f"Code {fac_code}")
            camp_code = details.get("campus_code") or "W"
            camp_name = resolve_campus_role(camp_code) or f"Campus {camp_code}"
            lvl_code = details.get("level_code") or "R"
            lvl_name = resolve_study_level_role(lvl_code) or f"Level {lvl_code}"
            prog_code = details.get("programme_code") or "N/A"

            verified_at = details.get("verified_at") or "Unknown"
            is_alumni = details.get("is_alumni")
            grad_year = details.get("graduated_year")
            card_expiry = details.get("card_expiry_date") or "*Not recorded*"
            email_hash = details.get("student_email_hash")

            status_str = "🎓 **TARUMT Alumni (Graduated)**" if is_alumni else "✅ **Active Verified Student**"
            email_status_str = (
                "🔒 **Email Verified (OTP Linked)**" if email_hash else "⚪ **Fast Verified (No Email Linked)**"
            )

            academic_body = (
                f"• **Status:** {status_str}\n"
                f"• **Email State:** {email_status_str}\n"
                f"• **Faculty:** `{fac_name}` (`{fac_code}`)\n"
                f"• **Campus:** `{camp_name}` (`{camp_code}`)\n"
                f"• **Study Level:** `{lvl_name}` (`{lvl_code}`)\n"
                f"• **Programme Code:** `{prog_code}`\n"
                f"• **Initial Verified At:** `{verified_at}`\n"
                f"• **Card Expiry Date:** `{card_expiry}`"
            )
            if is_alumni and grad_year:
                academic_body += f"\n• **Graduation Cohort:** `{grad_year}`"

            embed.add_field(name="📋 Verification & Academic Profile", value=academic_body, inline=False)
        else:
            embed.add_field(
                name="📋 Verification Profile",
                value="❌ **Not Verified**: No student record found in database.",
                inline=False,
            )

        # 2. Server Member Context & Roles (if in current server)
        if target_member:
            created_at_str = (
                target_member.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if target_member.created_at else "Unknown"
            )
            joined_at_str = (
                target_member.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC") if target_member.joined_at else "Unknown"
            )

            roles_list = [r.name for r in target_member.roles if r.name != "@everyone"]
            roles_disp = ", ".join(f"`{r}`" for r in roles_list[:12]) if roles_list else "*No custom roles*"
            if len(roles_list) > 12:
                roles_disp += f" *(+{len(roles_list) - 12} more)*"

            member_info = (
                f"• **Joined Server:** `{joined_at_str}`\n"
                f"• **Account Created:** `{created_at_str}`\n"
                f"• **Server Nickname:** `{target_member.nick or target_member.name}`\n"
                f"• **Current Roles ({len(roles_list)}):**\n  {roles_disp}"
            )
            embed.add_field(
                name=f"🏰 Server Member Details ({guild.name if guild else 'Current'})", value=member_info, inline=False
            )
        elif target_user:
            created_at_str = (
                target_user.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if target_user.created_at else "Unknown"
            )
            embed.add_field(
                name="🏰 Server Member Details",
                value=f"⚠️ User is not currently in this server.\n• **Account Created:** `{created_at_str}`",
                inline=False,
            )

        # 3. Academic Progression / Transitions History
        transitions = await self.cog.db.get_academic_transitions_for_user(user_id)
        if transitions:
            t_lines = []
            for t in transitions[-5:]:
                from_fac = FACULTY_ROLES.get(t.get("from_faculty_code") or "", t.get("from_faculty_code") or "?")
                to_fac = FACULTY_ROLES.get(t.get("to_faculty_code") or "", t.get("to_faculty_code") or "?")
                from_lvl = resolve_study_level_role(t.get("from_level_code") or "") or t.get("from_level_code") or "?"
                to_lvl = resolve_study_level_role(t.get("to_level_code") or "") or t.get("to_level_code") or "?"
                t_date = t.get("transitioned_at") or "Unknown"
                t_lines.append(f"• `{t_date}`: **{from_fac}** ({from_lvl}) ➔ **{to_fac}** ({to_lvl})")
            embed.add_field(
                name=f"🔄 Academic Transitions ({len(transitions)})", value="\n".join(t_lines), inline=False
            )

        # 4. Guest Review Ticket History
        if guild:
            latest_ticket = await self.cog.db.get_latest_guest_ticket_for_user(guild.id, user_id)
            if latest_ticket:
                seq = format_ticket_seq(latest_ticket.get("ticket_seq") or latest_ticket.get("ticket_id"))
                t_status = latest_ticket.get("status", "OPEN")
                t_created = latest_ticket.get("created_at", "N/A")
                t_reason = f'\n  *Reason:* "{latest_ticket.get("reason")}"' if latest_ticket.get("reason") else ""
                embed.add_field(
                    name="🎟️ Latest Guest Ticket",
                    value=f"• **Ticket #{seq}** — `{t_status}` (Created: `{t_created}`){t_reason}",
                    inline=False,
                )

        # 5. Audit Log History (Recent events involving user)
        user_audit_logs = await self.cog.db.get_user_audit_logs(user_id, limit=4)
        if user_audit_logs:
            audit_lines = []
            for log_row in user_audit_logs:
                ts, lvl, ev_type, g_name, _, msg = log_row
                g_str = f" [{g_name}]" if g_name else ""
                audit_lines.append(f"• `{ts}` **[{ev_type}]**{g_str}: {msg}")
            embed.add_field(name="📜 Recent Audit Activity", value="\n".join(audit_lines), inline=False)

        embed.set_footer(text=f"TARVeri User Inspector • Queried by {self.admin_user}")
        return embed

    async def build_randomtag_embed(self, guild: discord.Guild | None) -> discord.Embed:
        if not guild:
            return discord.Embed(
                title="🎲 Random Tagging", description="Must be run in a server.", color=discord.Color.red()
            )

        random_service = getattr(self.cog.bot, "random_tag_service", None)
        if not random_service:
            return discord.Embed(
                title="🎲 Random Tagging", description="Service not initialized.", color=discord.Color.red()
            )

        config = await random_service.get_config(guild.id)
        status_emoji = "🟢 Enabled" if config["is_enabled"] else "🔴 Disabled"
        words_preview = ", ".join(f"`{w}`" for w in config["words_list"][:8])

        embed = discord.Embed(
            title=f"🎲 Random Tagging Control Panel — {guild.name}",
            color=discord.Color.blue() if config["is_enabled"] else discord.Color.greyple(),
            description=(
                f"**Status:** {status_emoji}\n"
                f"**Target Channel:** Strictly `#general`\n"
                f"**Daily Limit:** `{config['current_daily_runs']} / {config['max_daily_runs']}` tags sent today\n"
                f"**Odds:** `1 in {config['chance_denominator']}` chance per tick\n"
                f"**Interval Window:** `{config['min_interval_minutes']}` - `{config['max_interval_minutes']}` mins (random with jitter)\n"
                f"**Rotation Mode:** `{config['word_rotation_mode'].replace('_', ' ').title()}`\n\n"
                f"**Configured Words ({len(config['words_list'])}):**\n{words_preview}"
            ),
        )
        embed.set_footer(text="Use the buttons below to toggle or customize settings.")
        return embed

    async def build_uptime_embed(self, guild: discord.Guild | None) -> discord.Embed:
        """Constructs a comprehensive system uptime, SLA metrics, and downtime history embed."""
        uptime_service = getattr(self.cog, "uptime_service", None) or getattr(self.cog.bot, "uptime_service", None)
        if not uptime_service or not hasattr(uptime_service, "get_sla_metrics"):
            return discord.Embed(
                title="⏱️ Uptime & SLA Tracking",
                description="Uptime monitoring service is not initialized.",
                color=discord.Color.red(),
            )

        res = uptime_service.get_sla_metrics()
        metrics = await res if inspect.isawaitable(res) else res
        if not isinstance(metrics, dict) or "sla_24h" not in metrics:
            return discord.Embed(
                title="⏱️ Uptime & SLA Tracking",
                description="Uptime metrics currently unavailable.",
                color=discord.Color.red(),
            )

        sla_24h = metrics["sla_24h"]
        sla_7d = metrics["sla_7d"]
        sla_30d = metrics["sla_30d"]

        if sla_24h["sla_percent"] >= 99.9:
            color = discord.Color.green()
        elif sla_24h["sla_percent"] >= 95.0:
            color = discord.Color.gold()
        else:
            color = discord.Color.red()

        embed = discord.Embed(
            title="⏱️ TARVeri System Uptime & SLA Performance",
            description="Continuous availability telemetry, downtime tracking, and SLA performance metrics.",
            color=color,
        )

        gateway_ping = f"{round(self.cog.bot.latency * 1000)}ms" if self.cog.bot.latency else "N/A"
        started_ts = metrics.get("started_at_timestamp")
        started_str = f"<t:{started_ts}:F> (<t:{started_ts}:R>)" if started_ts else metrics.get("started_at", "N/A")

        total_uptime_str = metrics.get("total_uptime_str", metrics["current_uptime_str"])
        longest_uptime_str = metrics.get("longest_uptime_str", metrics["current_uptime_str"])
        longest_badge = " *(🔥 Active Record)*" if metrics.get("longest_uptime_is_current") else ""

        session_info = (
            f"• **Current Session Uptime:** **{metrics['current_uptime_str']}**\n"
            f"• **All-Time Total Uptime:** **{total_uptime_str}**\n"
            f"• **Longest Uptime Record:** **{longest_uptime_str}**{longest_badge}\n"
            f"• **Session Started:** {started_str}\n"
            f"• **Session ID:** `{metrics['session_id']}`\n"
            f"• **Gateway Latency:** `{gateway_ping}`"
        )
        embed.add_field(name="🟢 Active Session Health", value=session_info, inline=False)

        all_time_sla = metrics.get("sla_all_time")
        sla_lines = [
            f"• **24-Hour SLA:** **`{sla_24h['sla_percent']:.3f}%`** — {sla_24h['grade']}",
            f"  └ Downtime: `{sla_24h['downtime_str']}` ({sla_24h['incidents']} incident(s))",
            f"• **7-Day SLA:** **`{sla_7d['sla_percent']:.3f}%`** — {sla_7d['grade']}",
            f"  └ Downtime: `{sla_7d['downtime_str']}` ({sla_7d['incidents']} incident(s))",
            f"• **30-Day SLA:** **`{sla_30d['sla_percent']:.3f}%`** — {sla_30d['grade']}",
            f"  └ Downtime: `{sla_30d['downtime_str']}` ({sla_30d['incidents']} incident(s))",
        ]
        if all_time_sla:
            sla_lines.append(
                f"• **All-Time SLA:** **`{all_time_sla['sla_percent']:.3f}%`** — {all_time_sla['grade']}\n"
                f"  └ Total Uptime: `{total_uptime_str}` • Total Downtime: `{all_time_sla['downtime_str']}`"
            )
        embed.add_field(name="📊 SLA Availability Scores", value="\n".join(sla_lines), inline=False)

        recent_incidents = metrics.get("recent_incidents", [])
        if recent_incidents:
            incident_lines = []
            for inc in recent_incidents[:5]:
                dt_type = inc["downtime_type"].replace("_", " ").title()
                dur_str = format_duration_seconds(inc["duration_seconds"])
                reason = inc.get("reason") or "Service restart / maintenance"
                incident_lines.append(f"• **{inc['started_at']}** — `{dur_str}` ({dt_type})\n  └ *{reason}*")
            embed.add_field(
                name="📉 Recent Downtime Incidents (Past 30 Days)",
                value="\n".join(incident_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="📉 Recent Downtime Incidents (Past 30 Days)",
                value="*No downtime incidents recorded in the last 30 days. Perfect availability!*",
                inline=False,
            )

        outage_service = getattr(self.cog.bot, "outage_service", None)
        outage_status = "Active (300s emergency limit)" if outage_service and outage_service.is_running else "Standby"
        embed.add_field(
            name="🛡️ High Availability & Watchdogs",
            value=(
                f"• **Heartbeat Daemon:** `Active (Every {uptime_service.heartbeat_interval_seconds}s)`\n"
                f"• **Outage Watchdog:** `{outage_status}`\n"
                f"• **Database Engine:** `SQLite WAL Checkpointed`"
            ),
            inline=False,
        )

        embed.set_footer(text="TARVeri High Availability SLA Engine • Click 'Refresh SLA Metrics' to update")
        return embed
