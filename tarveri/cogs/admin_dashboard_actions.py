"""Button and select handlers for the admin dashboard view."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

import discord

from tarveri.cogs.admin_dashboard_components import (
    AdminCategorySelect,
    ChannelSelectComponent,
    RoleSelectComponent,
)
from tarveri.cogs.admin_dashboard_modals import (
    AlumniRevokeModal,
    GuestRoleModal,
    RuntimeSettingsModal,
    UnverifyModal,
    UserLookupModal,
)
from tarveri.services.log_service import (
    archive_old_logs,
    list_daily_logs,
)
from tarveri.utils import schedule_ttl_delete

if TYPE_CHECKING:
    pass

logger = logging.getLogger("tarveri")


class DashboardActionsMixin:
    """Handles the dashboard's buttons and selects. Combined into AdminDashboardView."""

    # --- Button Callbacks ---

    async def _on_refresh_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await self.refresh_view(interaction)

    async def _on_switch_diagnose(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.current_category = "diagnose"
        await self.refresh_view(interaction)

    async def _on_run_diagnostics_now(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        guild = interaction.guild

        src_stats = await self.cog.service.restore_src_roles(guild)
        dedup_stats = await self.cog.service.reconcile_duplicate_roles(guild)
        warnings = self.cog.service.diagnose_guild_permissions(guild)
        reconcile_stats = await self.cog.service.reconcile_verified_members(guild)
        alumni_stats = await self.cog.service.reconcile_alumni_members(guild)

        guest_svc = getattr(self.cog.bot, "guest_service", None)
        thread_stats = {"checked": 0, "archived": 0, "failed": 0}
        if guest_svc and hasattr(guest_svc, "reconcile_resolved_ticket_threads"):
            res = guest_svc.reconcile_resolved_ticket_threads(guild)
            if inspect.isawaitable(res):
                thread_stats = await res
            elif isinstance(res, dict):
                thread_stats = res

        embed = discord.Embed(
            title=f"🩺 Server Diagnostics & Self-Healing Results — {guild.name}",
            color=discord.Color.green() if not warnings else discord.Color.orange(),
        )
        if warnings:
            embed.add_field(name="⚠️ Issues Detected", value="\n".join(f"• {w}" for w in warnings), inline=False)
        else:
            embed.add_field(name="✅ Health", value="All bot permissions and role positions are healthy.", inline=False)

        is_src_enabled = await self.cog.db.is_guild_src_roles_enabled(guild.id)
        if is_src_enabled:
            src_stats = await self.cog.service.restore_src_roles(guild)
            src_msg = f"• Restored **{src_stats.get('created', 0)}** missing SRC role(s) ({src_stats.get('existing', 0)} existing)"
        else:
            src_msg = "• *Disabled for this server (use 'Toggle SRC Roles' or `/admin src enable`)*"

        embed.add_field(
            name="🏛️ SRC Role Restorations",
            value=src_msg,
            inline=True,
        )
        embed.add_field(
            name="🧹 Duplicate Role Cleanup",
            value=f"• Deleted **{dedup_stats.get('deleted_roles', 0)}** role(s), Migrated **{dedup_stats.get('migrated_members', 0)}** member(s)",
            inline=True,
        )
        embed.add_field(
            name="🔄 Role Reconciliation",
            value=f"• Verified students: checked {reconcile_stats['checked']}, restored {reconcile_stats['restored']}\n• Alumni: checked {alumni_stats['checked']}, restored {alumni_stats['restored']}",
            inline=False,
        )
        if thread_stats.get("archived", 0) > 0:
            embed.add_field(
                name="🧵 Review Thread Cleanup",
                value=f"• Auto-archived **{thread_stats['archived']}** lingering resolved review thread(s)",
                inline=False,
            )

        await self.update_message(interaction, embed=embed)

    async def _on_toggle_src_roles_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        guild = interaction.guild
        current_state = await self.cog.db.is_guild_src_roles_enabled(guild.id)
        new_state = not current_state
        await self.cog.db.set_guild_src_roles_enabled(guild.id, new_state)

        if new_state:
            src_stats = await self.cog.service.restore_src_roles(guild, force=True)
            res_msg = (
                f"🟢 **SRC Role Management Enabled**\nRestored **{src_stats['created']}** missing faculty SRC role(s)."
            )
        else:
            res_msg = (
                "⚪ **SRC Role Management Disabled**\nSRC roles will not be auto-created or restored on this server."
            )

        await self.cog.db.log(
            "INFO",
            "CONFIG_SRC_ROLES",
            f"SRC role management toggled to {new_state} via Dashboard by {interaction.user}",
            guild=guild,
            user_id=interaction.user.id,
        )

        embed = await self.build_diagnose_embed(guild)
        embed.description = f"{res_msg}\n\n{embed.description or ''}".strip()
        await self.update_message(interaction, embed=embed)

    async def _on_remove_src_roles_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        guild = interaction.guild
        stats = await self.cog.service.remove_src_roles(guild)

        await self.cog.db.log(
            "INFO",
            "SRC_ROLES_REMOVED",
            f"SRC roles removed via Dashboard by {interaction.user} (Deleted: {stats['deleted']}, Failed: {stats['failed']})",
            guild=guild,
            user_id=interaction.user.id,
        )

        embed = await self.build_diagnose_embed(guild)
        embed.description = f"🗑️ **SRC Roles Removed**\nDeleted **{stats['deleted']}** faculty SRC role(s) from this server and disabled SRC role management."
        await self.update_message(interaction, embed=embed)

    async def _on_user_lookup_clicked(self, interaction: discord.Interaction) -> None:
        modal = UserLookupModal(self.cog, self)
        await interaction.response.send_modal(modal)

    async def _on_unverify_clicked(self, interaction: discord.Interaction) -> None:
        modal = UnverifyModal(self.cog, self)
        await interaction.response.send_modal(modal)

    async def _on_alumni_revoke_clicked(self, interaction: discord.Interaction) -> None:
        modal = AlumniRevokeModal(self.cog, self)
        await interaction.response.send_modal(modal)

    async def _on_runtime_settings_clicked(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RuntimeSettingsModal(self.cog, self))

    async def _on_set_guest_role_clicked(self, interaction: discord.Interaction) -> None:
        modal = GuestRoleModal(self.cog, self)
        await interaction.response.send_modal(modal)

    async def _on_set_admin_role_clicked(self, interaction: discord.Interaction) -> None:
        self.clear_items()
        self.add_item(AdminCategorySelect(self))
        self.add_item(RoleSelectComponent(self.cog, self))
        embed = await self.build_config_embed(interaction.guild)
        embed.set_footer(text="Select the Admin / Reviewer role from the menu below.")
        await self.update_message(interaction, embed=embed)

    async def _show_channel_select(self, interaction: discord.Interaction, config_type: str) -> None:
        self.clear_items()
        self.add_item(AdminCategorySelect(self))
        self.add_item(ChannelSelectComponent(self.cog, self, config_type))
        embed = (
            await self.build_config_embed(interaction.guild)
            if config_type != "panel_deploy"
            else await self.build_panel_embed(interaction.guild)
        )
        embed.set_footer(text=f"Select the target channel for {config_type.replace('_', ' ').title()}.")
        await self.update_message(interaction, embed=embed)

    async def _on_toggle_email_verification_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            return
        await interaction.response.defer()
        curr = await self.cog.db.is_guild_email_verification_enabled(interaction.guild.id)
        new_val = not curr
        await self.cog.db.set_guild_email_verification(interaction.guild.id, new_val)
        status_word = "**MANDATORY (Opted In)**" if new_val else "**OPTIONAL (Opted Out)**"
        await self.cog.db.log(
            "INFO",
            "GUILD_EMAIL_VERIFICATION_TOGGLED",
            f"Email verification requirement set to {new_val} by admin {interaction.user}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )
        self._rebuild_components()
        embed = await self.build_config_embed(interaction.guild)
        embed.description = f"📧 **Email verification requirement updated to {status_word}!**"
        await self.update_message(interaction, embed=embed)

    async def _on_toggle_email_enforcement_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            return
        await interaction.response.defer()
        curr = await self.cog.db.is_guild_email_enforcement_enabled(interaction.guild.id)
        new_val = not curr
        await self.cog.db.set_guild_email_enforcement(interaction.guild.id, new_val)
        status_word = (
            "🔴 **ENFORCED (Retroactive Role Stripping Active)**"
            if new_val
            else "🟢 **DISABLED (Existing Roles Preserved)**"
        )
        await self.cog.db.log(
            "INFO",
            "GUILD_EMAIL_ENFORCEMENT_TOGGLED",
            f"Email role enforcement set to {new_val} by admin {interaction.user}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )
        self._rebuild_components()
        embed = await self.build_config_embed(interaction.guild)
        embed.description = f"🛡️ **Email role enforcement policy updated to {status_word}!**"
        await self.update_message(interaction, embed=embed)

    async def _on_reset_config_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        await self.cog.db.set_guild_welcome_channel(interaction.guild.id, None)
        await self.cog.db.set_guild_help_channel(interaction.guild.id, None)
        await self.cog.db.set_guild_review_channel(interaction.guild.id, None)
        await self.cog.db.set_guild_guest_role(interaction.guild.id, "Guest")
        await self.cog.db.set_guild_admin_role(interaction.guild.id, None)
        await self.cog.db.set_guild_email_verification(interaction.guild.id, False)
        await self.cog.db.set_guild_email_enforcement(interaction.guild.id, False)

        verif_cog = self.cog.bot.get_cog("Verification")
        if verif_cog and hasattr(verif_cog, "invalidate_guild_cache"):
            verif_cog.invalidate_guild_cache(interaction.guild.id)

        embed = await self.build_config_embed(interaction.guild)
        embed.description = "🔄 **All server channels and roles have been reset to automatic auto-detection!**"
        await self.update_message(interaction, embed=embed)

    async def _on_refresh_tickets(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await self.refresh_view(interaction)

    async def _on_create_backup_clicked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        backup_path = await self.cog.db.create_backup()
        embed = await self.build_backup_embed(interaction.guild)
        embed.description = f"✅ **Database snapshot created successfully:** `{backup_path}`"
        await self.update_message(interaction, embed=embed)

    async def _on_restore_settings_clicked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        restored = await self.cog.db.restore_latest_guild_settings()
        embed = await self.build_backup_embed(interaction.guild)
        if restored:
            embed.description = f"✅ Restored `{restored}` guild settings record(s) from latest backup snapshot."
        else:
            embed.description = "ℹ️ No previous settings backup found to restore."
        await self.update_message(interaction, embed=embed)

    async def _on_archive_logs_clicked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        logs_dir = getattr(self.cog.bot, "settings", None) and self.cog.bot.settings.logs_dir or "logs"
        tz_name = getattr(self.cog.bot, "settings", None) and self.cog.bot.settings.timezone_name or "Asia/Kuala_Lumpur"
        results = archive_old_logs(logs_dir=logs_dir, older_than_days=10, tz_name=tz_name)
        embed = await self.build_logs_embed(interaction.guild)
        if results:
            total_saved = sum(r["space_saved_bytes"] for r in results) / 1024
            embed.description = (
                f"✅ Successfully created **{len(results)}** archive(s), saving **{total_saved:.1f} KB**."
            )
        else:
            embed.description = "ℹ️ No daily logs older than 10 days needed compression."
        await self.update_message(interaction, embed=embed)

    async def _on_tail_logs_clicked(self, interaction: discord.Interaction) -> None:
        logs_dir = getattr(self.cog.bot, "settings", None) and self.cog.bot.settings.logs_dir or "logs"
        tz_name = getattr(self.cog.bot, "settings", None) and self.cog.bot.settings.timezone_name or "Asia/Kuala_Lumpur"
        daily_logs = list_daily_logs(logs_dir=logs_dir, tz_name=tz_name)
        if not daily_logs:
            await interaction.response.send_message("⚠️ No active log file found.", ephemeral=True)
            return

        latest_log_path = daily_logs[0]["path"]
        try:
            with open(latest_log_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail_lines = lines[-15:] if len(lines) > 15 else lines
            content = "".join(tail_lines)
            if len(content) > 1900:
                content = content[-1900:]
            await interaction.response.send_message(
                f"📄 **Latest Logs** (`{daily_logs[0]['filename']}`):\n```text\n{content}\n```",
                ephemeral=True,
            )
            schedule_ttl_delete(interaction, delay=90.0)
        except Exception as e:
            logger.warning("Failed to read log file for admin dashboard: %s", e, exc_info=True)
            await interaction.response.send_message(f"❌ Failed to read log file: {e}", ephemeral=True)

    async def _on_deploy_here_clicked(self, interaction: discord.Interaction) -> None:
        target_ch = interaction.channel
        if not isinstance(target_ch, discord.TextChannel):
            await interaction.response.send_message("❌ Current channel is not a text channel.", ephemeral=True)
            return

        from tarveri.cogs.guest_cog import VerificationGatewayView, build_gateway_panel_embed

        guest_service = getattr(self.cog.bot, "guest_service", None)
        if not guest_service:
            from tarveri.services.guest_service import GuestService

            guest_service = GuestService(
                bot=self.cog.bot,
                db=self.cog.db,
                rate_limiter=self.cog.rate_limiter,
                admin_role_name=self.cog.admin_role_name,
            )

        email_required = (
            await self.cog.db.is_guild_email_verification_enabled(interaction.guild.id) if interaction.guild else False
        )
        guild_name = interaction.guild.name if interaction.guild else "the Server"
        embed = build_gateway_panel_embed(guild_name=guild_name, require_email=email_required)
        gateway_view = VerificationGatewayView(self.cog.service, guest_service)
        await target_ch.send(embed=embed, view=gateway_view)

        await interaction.response.send_message(
            f"✅ Verification gateway panel posted to {target_ch.mention}!", ephemeral=True
        )
        schedule_ttl_delete(interaction, delay=60.0)

    async def _on_check_updates_clicked(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        embed = await self.build_updates_embed(interaction.guild)
        await self.update_message(interaction, embed=embed)

    async def _on_resync_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        guild = interaction.guild
        reconcile_stats = await self.cog.service.reconcile_verified_members(guild)
        alumni_stats = await self.cog.service.reconcile_alumni_members(guild)
        embed = await self.build_updates_embed(guild)
        embed.description = (
            f"✅ **Mutual Server Role Resynchronization Complete!**\n"
            f"• Verified Students: checked {reconcile_stats['checked']}, restored {reconcile_stats['restored']}\n"
            f"• Alumni: checked {alumni_stats['checked']}, restored {alumni_stats['restored']}"
        )
        await self.update_message(interaction, embed=embed)

    async def _on_randomtag_toggle_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        random_service = getattr(self.cog.bot, "random_tag_service", None)
        if not random_service:
            return
        config = await random_service.get_config(interaction.guild.id)
        new_state = not config["is_enabled"]
        await random_service.update_config(interaction.guild.id, is_enabled=new_state)
        embed = await self.build_randomtag_embed(interaction.guild)
        await self.update_message(interaction, embed=embed)

    async def _on_randomtag_config_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        random_service = getattr(self.cog.bot, "random_tag_service", None)
        if not random_service:
            return
        from tarveri.cogs.random_tag_cog import RandomTagConfigModal

        config = await random_service.get_config(interaction.guild.id)
        modal = RandomTagConfigModal(random_service, config)
        await interaction.response.send_modal(modal)

    async def _on_randomtag_mode_clicked(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        await interaction.response.defer()
        random_service = getattr(self.cog.bot, "random_tag_service", None)
        if not random_service:
            return
        config = await random_service.get_config(interaction.guild.id)
        new_mode = "round_robin" if config["word_rotation_mode"] == "random" else "random"
        await random_service.update_config(interaction.guild.id, word_rotation_mode=new_mode)
        embed = await self.build_randomtag_embed(interaction.guild)
        await self.update_message(interaction, embed=embed)

    async def _on_refresh_uptime_clicked(self, interaction: discord.Interaction) -> None:
        """Refreshes the live SLA metrics and latency."""
        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = await self.build_uptime_embed(interaction.guild)
        await self.update_message(interaction, embed=embed)
