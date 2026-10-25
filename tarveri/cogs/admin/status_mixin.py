"""Dashboard, diagnostics, logs, backups, update checks and command sync."""

from __future__ import annotations

import inspect
import logging

import discord
from discord import app_commands

from tarveri.cogs.admin.groups import admin_group
from tarveri.cogs.admin_dashboard import AdminDashboardView
from tarveri.cogs.random_tag_cog import RandomTagDashboardView
from tarveri.config import (
    FACULTY_ROLES,
)
from tarveri.services.log_service import (
    archive_old_logs,
    list_daily_logs,
    list_log_archives,
)
from tarveri.services.update_checker import UpdateCheckerService
from tarveri.utils import schedule_ttl_delete

logger = logging.getLogger("tarveri")


class AdminStatusCommands:
    """Dashboard, diagnostics, logs, backups, update checks and command sync."""

    # ==========================================
    # 🛡️ 1. Interactive Dashboard Launcher
    # ==========================================

    @admin_group.command(
        name="dashboard",
        description="Open the interactive TARVeri Administrator Control Center dashboard.",
    )
    @app_commands.default_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction) -> None:
        """Launches the rich interactive Administrator Control Center UI."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        view = AdminDashboardView(cog=self, admin_user=interaction.user, initial_category="overview")
        embed = await view.build_overview_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @admin_group.command(
        name="uptime",
        description="View continuous bot uptime, downtime detection history, and SLA availability scores.",
    )
    @app_commands.default_permissions(administrator=True)
    async def uptime(self, interaction: discord.Interaction) -> None:
        """Launches the Uptime and SLA Performance dashboard."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        view = AdminDashboardView(cog=self, admin_user=interaction.user, initial_category="uptime")
        embed = await view.build_uptime_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def randomtag(self, interaction: discord.Interaction) -> None:
        """Launches the Random Tagging configuration dashboard."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command must be executed within a Discord server.", ephemeral=True
            )
            return

        random_tag_service = getattr(self.bot, "random_tag_service", None)
        if not random_tag_service:
            await interaction.response.send_message(
                "❌ Random Tagging Service is not currently active.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        config = await random_tag_service.get_config(interaction.guild.id)
        status_emoji = "🟢 Enabled" if config["is_enabled"] else "🔴 Disabled"
        words_preview = ", ".join(f"`{w}`" for w in config["words_list"][:8])

        embed = discord.Embed(
            title=f"🎲 Random Tagging Control Panel — {interaction.guild.name}",
            color=discord.Color.blue() if config["is_enabled"] else discord.Color.greyple(),
            description=(
                f"**Status:** {status_emoji}\n"
                f"**Target Channel:** Strictly `#general`\n"
                f"**Daily Limit:** `{config['current_daily_runs']} / {config['max_daily_runs']}` tags sent today\n"
                f"**Odds:** `1 in {config['chance_denominator']}` chance per tick\n"
                f"**Interval Window:** `{config['min_interval_minutes']}` - `{config['max_interval_minutes']}` mins (highly randomized with jitter)\n"
                f"**Rotation Mode:** `{config['word_rotation_mode'].replace('_', ' ').title()}`\n\n"
                f"**Configured Words ({len(config['words_list'])}):**\n{words_preview}"
            ),
        )
        embed.set_footer(text="Click the buttons below to toggle or customize settings.")

        view = RandomTagDashboardView(random_tag_service, interaction.guild.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ==========================================
    # 📊 2. Statistics & Metrics
    # ==========================================

    @admin_group.command(name="stats", description="View student verification statistics and server metrics.")
    @app_commands.default_permissions(administrator=True)
    async def stats(self, interaction: discord.Interaction) -> None:
        """Displays total verifications, faculty breakdown, and recent activity."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        total = await self.db.total_verified()
        total_alumni = await self.db.count_alumni()
        faculty_counts = await self.db.counts_by_faculty()
        last_24h = await self.db.verified_in_last(24)
        last_7d = await self.db.verified_in_last(24 * 7)

        embed = discord.Embed(
            title="📊 TARVeri — Verification Statistics",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Total Verified", value=f"**{total}** students", inline=True)
        embed.add_field(name="Graduated Alumni", value=f"**{total_alumni}** alumni", inline=True)
        embed.add_field(name="Past 24 Hours", value=f"**{last_24h}** new", inline=True)
        embed.add_field(name="Past 7 Days", value=f"**{last_7d}** new", inline=True)

        email_stats = await self.db.get_email_verification_stats(interaction.guild.id if interaction.guild else None)
        embed.add_field(
            name="Email Verified",
            value=f"**{email_stats['email_verified_students']}** / **{total}** ({email_stats['email_verified_rate']}%)",
            inline=True,
        )

        if faculty_counts:
            breakdown_lines = []
            for f_code, count in faculty_counts:
                faculty_name = FACULTY_ROLES.get(f_code, f"Code {f_code}")
                percentage = (count / total * 100) if total > 0 else 0
                breakdown_lines.append(f"• **{faculty_name}** (`{f_code}`): {count} ({percentage:.1f}%)")
            embed.add_field(name="Faculty Breakdown", value="\n".join(breakdown_lines), inline=False)
        else:
            embed.add_field(name="Faculty Breakdown", value="No verifications recorded yet.", inline=False)

        if interaction.guild:
            guild_settings = await self.db.get_guild_settings(interaction.guild.id)
            w_id = guild_settings[0] if guild_settings else None
            h_id = guild_settings[1] if guild_settings else None
            g_role = (
                guild_settings[2]
                if guild_settings and len(guild_settings) > 2 and guild_settings[2]
                else "Guest(Approved)"
            )
            r_id = guild_settings[3] if guild_settings and len(guild_settings) > 3 else None
            is_email_opted_in = bool(guild_settings[5]) if guild_settings and len(guild_settings) > 5 else False

            w_ch = interaction.guild.get_channel(w_id) if w_id else None
            h_ch = interaction.guild.get_channel(h_id) if h_id else None
            r_ch = interaction.guild.get_channel(r_id) if r_id else None

            w_display = w_ch.mention if w_ch else (f"`ID: {w_id}`" if w_id else "*Auto-detect*")
            h_display = h_ch.mention if h_ch else (f"`ID: {h_id}`" if h_id else "*Auto-detect*")
            r_display = r_ch.mention if r_ch else (f"`ID: {r_id}`" if r_id else "*Auto-detect*")

            adm_role = (
                guild_settings[4]
                if guild_settings and len(guild_settings) > 4 and guild_settings[4]
                else f"*Auto-detect ({self.admin_role_name})*"
            )

            email_policy_str = "Mandatory (Opted In)" if is_email_opted_in else "Optional (Opted Out)"

            embed.add_field(name="Welcome Channel", value=w_display, inline=True)
            embed.add_field(name="Help Channel", value=h_display, inline=True)
            embed.add_field(name="Guest Role", value=f"`{g_role}`", inline=True)
            embed.add_field(name="Review Channel", value=r_display, inline=True)
            embed.add_field(name="Admin / Review Role", value=f"`{adm_role}`", inline=True)
            embed.add_field(name="Email Verification Policy", value=f"`{email_policy_str}`", inline=True)

        embed.set_footer(text=f"TARVeri Bot • Active in {len(self.bot.guilds)} servers")
        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    # ==========================================
    # 🩺 3. Diagnostics & Self-Healing
    # ==========================================

    @admin_group.command(
        name="diagnose",
        description="Run self-healing diagnostics and verify server permissions, roles, and channels.",
    )
    @app_commands.default_permissions(administrator=True)
    async def diagnose(self, interaction: discord.Interaction) -> None:
        """Runs role hierarchy check, channel validity checks, and auto-reconciliation."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used within a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        src_stats = await self.service.restore_src_roles(guild)
        dedup_stats = await self.service.reconcile_duplicate_roles(guild)
        warnings = self.service.diagnose_guild_permissions(guild)
        reconcile_stats = await self.service.reconcile_verified_members(guild)
        alumni_stats = await self.service.reconcile_alumni_members(guild)

        guest_svc = getattr(self.bot, "guest_service", None)
        thread_stats = {"checked": 0, "archived": 0, "failed": 0}
        if guest_svc and hasattr(guest_svc, "reconcile_resolved_ticket_threads"):
            res = guest_svc.reconcile_resolved_ticket_threads(guild)
            if inspect.isawaitable(res):
                thread_stats = await res
            elif isinstance(res, dict):
                thread_stats = res

        # Check channel configurations
        settings = await self.db.get_guild_settings(guild.id)
        w_id = settings[0] if settings else None
        h_id = settings[1] if settings else None
        r_id = settings[3] if settings and len(settings) > 3 else None

        channel_status = []
        if w_id:
            w_ch = guild.get_channel(w_id)
            if not w_ch:
                await self.db.clear_stale_channel_setting(guild.id, "welcome")
                channel_status.append("⚠️ Stale welcome channel ID was detected and auto-cleared.")
            else:
                channel_status.append(f"✅ Welcome channel: {w_ch.mention}")
        else:
            channel_status.append("ℹ️ Welcome channel: *Auto-detected*")

        if h_id:
            h_ch = guild.get_channel(h_id)
            if not h_ch:
                await self.db.clear_stale_channel_setting(guild.id, "help")
                channel_status.append("⚠️ Stale help channel ID was detected and auto-cleared.")
            else:
                channel_status.append(f"✅ Help channel: {h_ch.mention}")
        else:
            channel_status.append("ℹ️ Help channel: *Auto-detected*")

        if r_id:
            r_ch = guild.get_channel(r_id)
            if not r_ch:
                await self.db.clear_stale_channel_setting(guild.id, "review")
                channel_status.append("⚠️ Stale review channel ID was detected and auto-cleared.")
            else:
                channel_status.append(f"✅ Review channel: {r_ch.mention}")
        else:
            channel_status.append("ℹ️ Review channel: *Auto-detected*")

        is_email_opted_in = await self.db.is_guild_email_verification_enabled(guild.id)
        email_policy_label = "Mandatory (Opted In)" if is_email_opted_in else "Optional (Opted Out)"
        channel_status.append(f"📧 Email Verification Policy: **{email_policy_label}**")

        embed = discord.Embed(
            title="🛡️ TARVeri — Server Health & Diagnostics",
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
                value="All required permissions and role positions are properly configured.",
                inline=False,
            )

        if src_stats.get("created", 0) > 0:
            embed.add_field(
                name="🏛️ SRC Roles Self-Healing",
                value=f"• Restored **{src_stats['created']}** missing faculty SRC role(s)",
                inline=False,
            )

        if (
            dedup_stats.get("deleted_roles", 0) > 0
            or dedup_stats.get("migrated_members", 0) > 0
            or dedup_stats.get("failed", 0) > 0
        ):
            embed.add_field(
                name="🧹 Duplicate Role Cleanup & Migration",
                value=(
                    f"• Deleted **{dedup_stats.get('deleted_roles', 0)}** duplicate role(s)\n"
                    f"• Migrated **{dedup_stats.get('migrated_members', 0)}** member(s) to primary role\n"
                    f"• Blocked / hierarchy errors: **{dedup_stats.get('failed', 0)}**"
                ),
                inline=False,
            )

        embed.add_field(
            name="🔄 Self-Healing Member & Alumni Reconciliation",
            value=(
                f"• Verified students: checked **{reconcile_stats['checked']}**, restored **{reconcile_stats['restored']}**, failed **{reconcile_stats['failed']}**\n"
                f"• Graduated alumni: checked **{alumni_stats['checked']}**, restored **{alumni_stats['restored']}**, failed **{alumni_stats['failed']}**"
            ),
            inline=False,
        )

        if thread_stats.get("archived", 0) > 0:
            embed.add_field(
                name="🧵 Review Thread Cleanup",
                value=f"• Auto-archived **{thread_stats['archived']}** lingering resolved review thread(s)",
                inline=False,
            )

        dlq_svc = self.dead_letter_service or getattr(self.bot, "dead_letter_service", None)
        if dlq_svc and hasattr(dlq_svc, "get_health_status"):
            res_dlq = dlq_svc.get_health_status()
            dlq_health = await res_dlq if inspect.isawaitable(res_dlq) else res_dlq
            if isinstance(dlq_health, dict) and dlq_health.get("warning"):
                embed.add_field(
                    name="📬 Dead Letter Queue Notice",
                    value=f"• {dlq_health['warning']}",
                    inline=False,
                )

        embed.add_field(
            name="📡 Channel Configuration Health",
            value="\n".join(channel_status),
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=90.0)

    # ==========================================
    # 💾 8. Database Backups
    # ==========================================

    @admin_group.command(
        name="backup",
        description="Manage SQLite database snapshots, backups, and settings restoration.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        action="Backup operation to perform (create, list, or restore_settings)",
        backup_file="Optional specific backup filename to restore (default: most recent)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Create Snapshot Now", value="create"),
            app_commands.Choice(name="List Available Backups", value="list"),
            app_commands.Choice(name="Restore Previous Settings", value="restore_settings"),
        ]
    )
    async def backup(
        self,
        interaction: discord.Interaction,
        action: str = "create",
        backup_file: str | None = None,
    ) -> None:
        """Manages SQLite database backups and guild settings restoration."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        action_val = action.value if hasattr(action, "value") else str(action)

        if action_val == "create":
            backup_path = await self.db.create_backup()
            max_b = getattr(self.bot, "settings", None) and self.bot.settings.max_backups or 10
            await interaction.followup.send(
                f"✅ **Database backup created successfully.**\n"
                f"• Snapshot file: `{backup_path}`\n"
                f"• Retention: up to **{max_b}** most recent backups are automatically kept in `backups/`.",
                ephemeral=True,
            )
            schedule_ttl_delete(interaction, delay=60.0)

        elif action_val == "list":
            settings = getattr(self.bot, "settings", None)
            backup_dir = (
                settings.backup_dir
                if settings and isinstance(getattr(settings, "backup_dir", None), str)
                else "backups"
            )
            backups = self.db.list_backups(backup_dir=backup_dir)
            if not backups:
                await interaction.followup.send("ℹ️ No backups currently found.", ephemeral=True)
                schedule_ttl_delete(interaction, delay=60.0)
                return

            embed = discord.Embed(
                title=f"💾 Database Backups (`{backup_dir}/`)",
                description=f"Showing **{len(backups)}** available snapshot(s):",
                color=discord.Color.blue(),
            )
            for b in backups[:10]:
                size_kb = b.get("size_bytes", 0) / 1024 if "size_bytes" in b else b.get("size_kb", 0)
                time_str = b.get("timestamp") or b.get("created_at") or "N/A"
                embed.add_field(
                    name=f"📦 {b['filename']}",
                    value=f"• Size: `{size_kb:.1f} KB`\n• Created: `{time_str}`",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
            schedule_ttl_delete(interaction, delay=90.0)

        elif action_val == "restore_settings":
            if backup_file:
                res = await self.db.restore_guild_settings_from_backup(backup_file)
                count = res.get("restored_guilds", 0) if isinstance(res, dict) else 0
            else:
                count = await self.db.restore_latest_guild_settings()
            if count:
                await interaction.followup.send(
                    f"✅ **Successfully restored `{count}` guild settings records** from backup.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send("⚠️ No suitable backup found to restore settings from.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)

    # ==========================================
    # 📋 9. Daily Logs & Historical Archives
    # ==========================================

    @admin_group.command(
        name="logs",
        description="Inspect daily log files, view compressed 10-day archives, or trigger log rotation.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        action="Log operation to perform (list: view files & archives, archive: trigger compression, recent: tail log)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="List Daily Logs & 10-Day Archives", value="list"),
            app_commands.Choice(name="Run 10-Day Log Archival (.tar.gz)", value="archive"),
            app_commands.Choice(name="View Recent Active Log Lines", value="recent"),
        ]
    )
    async def logs(
        self,
        interaction: discord.Interaction,
        action: str = "list",
    ) -> None:
        """Inspects daily log files in logs/, compressed 10-day archives, or forces immediate rotation."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        action_val = action.value if hasattr(action, "value") else str(action)
        settings = getattr(self.bot, "settings", None)
        logs_dir = settings.logs_dir if settings and isinstance(getattr(settings, "logs_dir", None), str) else "logs"
        tz_name = (
            settings.timezone_name
            if settings and isinstance(getattr(settings, "timezone_name", None), str)
            else "Asia/Kuala_Lumpur"
        )

        if action_val == "list":
            daily_logs = list_daily_logs(logs_dir=logs_dir, tz_name=tz_name)
            archives = list_log_archives(logs_dir=logs_dir)

            embed = discord.Embed(
                title=f"📁 TARVeri Logs & Historical Archives (`{logs_dir}/`)",
                color=discord.Color.blue(),
            )

            if daily_logs:
                daily_desc = []
                for dl in daily_logs[:7]:
                    size_kb = dl["size_bytes"] / 1024
                    daily_desc.append(f"• 📄 `{dl['filename']}` — {size_kb:.1f} KB ({dl['lines']} lines)")
                embed.add_field(
                    name=f"📅 Active Daily Logs ({len(daily_logs)} total)",
                    value="\n".join(daily_desc) if daily_desc else "None",
                    inline=False,
                )
            else:
                embed.add_field(name="📅 Active Daily Logs", value="No daily log files found.", inline=False)

            if archives:
                archive_desc = []
                for ar in archives[:7]:
                    size_kb = ar["size_bytes"] / 1024
                    archive_desc.append(f"• 📦 `{ar['filename']}` — {size_kb:.1f} KB ({ar['file_count']} logs bundled)")
                embed.add_field(
                    name=f"🗜️ 10-Day Compressed Archives ({len(archives)} total in `{logs_dir}/archives/`)",
                    value="\n".join(archive_desc) if archive_desc else "None",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="🗜️ 10-Day Compressed Archives",
                    value="No archives created yet (logs $>10$ days old are grouped and compressed).",
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)
            schedule_ttl_delete(interaction, delay=90.0)

        elif action_val == "archive":
            results = archive_old_logs(
                logs_dir=logs_dir,
                older_than_days=getattr(self.bot, "settings", None) and self.bot.settings.log_archive_days or 10,
                tz_name=tz_name,
            )

            if not results:
                await interaction.followup.send(
                    "ℹ️ No uncompressed daily log files older than 10 days found to archive.",
                    ephemeral=True,
                )
                schedule_ttl_delete(interaction, delay=60.0)
                return

            total_saved_kb = sum(r["space_saved_bytes"] for r in results) / 1024
            total_files = sum(len(r["files_archived"]) for r in results)

            embed = discord.Embed(
                title="🗜️ Log Archival & Compression Completed",
                description=(
                    f"Successfully grouped and compressed **{total_files}** daily log file(s) "
                    f"into **{len(results)}** 10-day `.tar.gz` archive(s).\n"
                    f"💾 **Space Saved:** `{total_saved_kb:.1f} KB`"
                ),
                color=discord.Color.green(),
            )
            for r in results[:10]:
                ar_size_kb = r["archive_bytes"] / 1024
                embed.add_field(
                    name=f"📦 `{r['archive_name']}`",
                    value=f"• **Period:** `{r['period_tag']}`\n• **Files Bundled:** {len(r['files_archived'])}\n• **Archive Size:** `{ar_size_kb:.1f} KB`",
                    inline=False,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)
            schedule_ttl_delete(interaction, delay=90.0)

        elif action_val == "recent":
            daily_logs = list_daily_logs(logs_dir=logs_dir, tz_name=tz_name)
            if not daily_logs:
                await interaction.followup.send("⚠️ No active log file found.", ephemeral=True)
                schedule_ttl_delete(interaction, delay=60.0)
                return

            latest_log_path = daily_logs[0]["path"]
            try:
                with open(latest_log_path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                tail_lines = lines[-15:] if len(lines) > 15 else lines
                content = "".join(tail_lines)
                if len(content) > 1900:
                    content = content[-1900:]

                await interaction.followup.send(
                    f"📄 **Latest Logs** (`{daily_logs[0]['filename']}`):\n```text\n{content}\n```",
                    ephemeral=True,
                )
            except Exception as e:
                logger.warning("Failed to read daily log file: %s", e, exc_info=True)
                await interaction.followup.send(f"❌ Failed to read log file: {e}", ephemeral=True)
            schedule_ttl_delete(interaction, delay=90.0)

    # ==========================================
    # 🔍 10. Audit Log Query
    # ==========================================

    @admin_group.command(name="audit", description="Query recent audit log entries.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        limit="Number of log records to retrieve (1-50, default 10)",
        event_type="Filter by event type (e.g. VERIFICATION_SUCCESS, MEMBER_UNVERIFIED)",
    )
    async def audit(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 50] = 10,
        event_type: str | None = None,
    ) -> None:
        """Retrieves recent audit log records with filtering."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        logs = await self.db.recent_audit(limit=limit, event_type=event_type)
        if not logs:
            await interaction.followup.send("ℹ️ No audit log records found.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        embed = discord.Embed(
            title="📜 TARVeri — Audit Log Entries",
            description=f"Showing the last **{len(logs)}** log event(s):",
            color=discord.Color.dark_gray(),
        )

        for log_row in logs:
            timestamp, level, ev_type, guild_name, user_id, msg = log_row
            guild_str = f"Guild: {guild_name}" if guild_name else "Global"
            user_str = f"User: <@{user_id}>" if user_id else "System"

            embed.add_field(
                name=f"[{level}] {ev_type} • {timestamp}",
                value=f"{msg}\n*{guild_str} | {user_str}*",
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=90.0)

    # ==========================================
    # 🔄 12. Updates Checker
    # ==========================================

    @admin_group.command(
        name="updates",
        description="Check if bot updates are available from git upstream.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(stream="Optional branch/stream name to check against (defaults to configured stream)")
    async def updates(self, interaction: discord.Interaction, stream: str | None = None) -> None:
        """Checks git upstream for new commits on the configured or specified branch."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        checker = self.update_checker
        if not checker:
            checker = UpdateCheckerService(
                bot=self.bot,
                db=self.db,
                update_stream=stream or "auto",
            )

        is_avail, count, local_h, remote_h, target_stream = await checker.check_for_updates(custom_stream=stream)

        embed = discord.Embed(
            title="🔄 TARVeri Update Status",
            color=discord.Color.green() if not is_avail else discord.Color.gold(),
        )
        embed.add_field(name="Target Stream", value=f"`{target_stream}`", inline=False)
        embed.add_field(name="Local Version", value=f"`{local_h[:7]}`" if local_h else "*Unknown*", inline=True)
        embed.add_field(name="Remote Version", value=f"`{remote_h[:7]}`" if remote_h else "*Unknown*", inline=True)

        if is_avail:
            branch_arg = target_stream.replace("origin/", "").strip()
            embed.description = (
                f"🔔 **Update available!** Remote is **{count} commit(s)** ahead.\n\n"
                f"To update, run on your server terminal:\n"
                f"```bash\n./scripts/update.sh {branch_arg}\n```"
            )
        else:
            if not remote_h:
                embed.description = (
                    f"⚠️ Could not resolve remote branch `{target_stream}`. Check if the branch exists on remote."
                )
            else:
                embed.description = "✅ TARVeri is up to date on this stream!"

        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    # Legacy alias
    async def check_updates(self, interaction: discord.Interaction, stream: str | None = None) -> None:
        await self.updates(interaction, stream=stream)

    # ==========================================
    # ⚡ 13. Sync Commands
    # ==========================================

    @admin_group.command(
        name="sync_commands",
        description="Synchronize application slash commands with Discord.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        clean_duplicates="Clear guild-specific command overrides before syncing",
        guild_only="Sync only to the current server (faster) instead of globally",
    )
    async def sync_commands(
        self,
        interaction: discord.Interaction,
        clean_duplicates: bool = False,
        guild_only: bool = False,
    ) -> None:
        """Synchronizes application commands with Discord API."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if clean_duplicates and interaction.guild:
                self.bot.tree.clear_commands(guild=interaction.guild)

            if guild_only and interaction.guild:
                self.bot.tree.copy_global_to(guild=interaction.guild)
                synced = await self.bot.tree.sync(guild=interaction.guild)
                scope = f"to server '{interaction.guild.name}'"
            else:
                synced = await self.bot.tree.sync()
                scope = "globally"

            msg_suffix = "Duplicates cleared prior to sync." if clean_duplicates else ""
            await interaction.followup.send(
                f"✅ Successfully synced {len(synced)} command(s) {scope}.\n{msg_suffix}",
                ephemeral=True,
            )
        except Exception as e:
            logger.warning("Failed to sync commands: %s", e, exc_info=True)
            await interaction.followup.send(f"❌ Failed to sync commands: {e}", ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)
