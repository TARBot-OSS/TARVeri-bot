"""Interactive admin dashboard. The view combines embed builders and handlers from sibling modules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import ui

from tarveri.cogs.admin_dashboard_actions import DashboardActionsMixin
from tarveri.cogs.admin_dashboard_components import (
    AdminCategorySelect,
    ChannelSelectComponent,
    RoleSelectComponent,
)
from tarveri.cogs.admin_dashboard_embeds import DashboardEmbedsMixin
from tarveri.cogs.admin_dashboard_modals import (
    AlumniRevokeModal,
    GuestRoleModal,
    RuntimeSettingsModal,
    UnverifyModal,
    UserLookupModal,
    _extract_user_id,
)

if TYPE_CHECKING:
    from tarveri.cogs.admin_cog import AdminCog

logger = logging.getLogger("tarveri")


__all__ = [
    "AdminCategorySelect",
    "AdminDashboardView",
    "AlumniRevokeModal",
    "ChannelSelectComponent",
    "GuestRoleModal",
    "RoleSelectComponent",
    "RuntimeSettingsModal",
    "UnverifyModal",
    "UserLookupModal",
    "_extract_user_id",
]


class AdminDashboardView(DashboardEmbedsMixin, DashboardActionsMixin, ui.View):
    def __init__(
        self,
        cog: AdminCog,
        admin_user: discord.User | discord.Member,
        initial_category: str = "overview",
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.admin_user = admin_user
        self.current_category = initial_category
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.admin_user.id or self.cog._check_admin(interaction):
            return True
        await interaction.response.send_message(
            "❌ You do not have permission to interact with this control center.", ephemeral=True
        )
        return False

    def _rebuild_components(self) -> None:
        self.clear_items()
        self.add_item(AdminCategorySelect(self))

        # Dynamic action buttons depending on the active category
        if self.current_category == "overview":
            btn_refresh = ui.Button(label="Refresh Metrics", style=discord.ButtonStyle.secondary, emoji="🔄")
            btn_refresh.callback = self._on_refresh_clicked
            self.add_item(btn_refresh)

            btn_diagnose = ui.Button(label="Run Diagnostics", style=discord.ButtonStyle.primary, emoji="🩺")
            btn_diagnose.callback = self._on_switch_diagnose
            self.add_item(btn_diagnose)

        elif self.current_category == "config":
            btn_set_welcome = ui.Button(label="Set Welcome Channel", style=discord.ButtonStyle.secondary, emoji="📢")
            btn_set_welcome.callback = lambda i: self._show_channel_select(i, "welcome")
            self.add_item(btn_set_welcome)

            btn_set_help = ui.Button(label="Set Help Channel", style=discord.ButtonStyle.secondary, emoji="❓")
            btn_set_help.callback = lambda i: self._show_channel_select(i, "help")
            self.add_item(btn_set_help)

            btn_set_review = ui.Button(label="Set Review Channel", style=discord.ButtonStyle.secondary, emoji="🎫")
            btn_set_review.callback = lambda i: self._show_channel_select(i, "review")
            self.add_item(btn_set_review)

            btn_set_guest_role = ui.Button(label="Set Guest Role", style=discord.ButtonStyle.secondary, emoji="👥")
            btn_set_guest_role.callback = self._on_set_guest_role_clicked
            self.add_item(btn_set_guest_role)

            btn_set_admin_role = ui.Button(label="Set Admin Role", style=discord.ButtonStyle.secondary, emoji="🛡️")
            btn_set_admin_role.callback = self._on_set_admin_role_clicked
            self.add_item(btn_set_admin_role)

            btn_runtime = ui.Button(
                label="Join Protection & Audit Tuning", style=discord.ButtonStyle.secondary, emoji="🛡️"
            )
            btn_runtime.callback = self._on_runtime_settings_clicked
            self.add_item(btn_runtime)

            btn_toggle_email = ui.Button(
                label="Toggle Email Verification", style=discord.ButtonStyle.primary, emoji="📧"
            )
            btn_toggle_email.callback = self._on_toggle_email_verification_clicked
            self.add_item(btn_toggle_email)

            btn_toggle_email_enforce = ui.Button(
                label="Toggle Role Enforcement", style=discord.ButtonStyle.secondary, emoji="🛡️"
            )
            btn_toggle_email_enforce.callback = self._on_toggle_email_enforcement_clicked
            self.add_item(btn_toggle_email_enforce)

            btn_reset_auto = ui.Button(label="Reset to Auto-Detect", style=discord.ButtonStyle.danger, emoji="🔄")
            btn_reset_auto.callback = self._on_reset_config_clicked
            self.add_item(btn_reset_auto)

        elif self.current_category == "diagnose":
            btn_run_diag = ui.Button(label="Run Diagnostics Now", style=discord.ButtonStyle.success, emoji="🩺")
            btn_run_diag.callback = self._on_run_diagnostics_now
            self.add_item(btn_run_diag)

            btn_toggle_src = ui.Button(label="Toggle SRC Roles", style=discord.ButtonStyle.primary, emoji="🏛️")
            btn_toggle_src.callback = self._on_toggle_src_roles_clicked
            self.add_item(btn_toggle_src)

            btn_remove_src = ui.Button(label="Remove SRC Roles", style=discord.ButtonStyle.danger, emoji="🗑️")
            btn_remove_src.callback = self._on_remove_src_roles_clicked
            self.add_item(btn_remove_src)

        elif self.current_category == "moderation":
            btn_lookup = ui.Button(label="Lookup Member Info", style=discord.ButtonStyle.primary, emoji="🔍")
            btn_lookup.callback = self._on_user_lookup_clicked
            self.add_item(btn_lookup)

            btn_unverify = ui.Button(label="Unverify Student", style=discord.ButtonStyle.danger, emoji="❌")
            btn_unverify.callback = self._on_unverify_clicked
            self.add_item(btn_unverify)

            btn_alumni_revoke = ui.Button(label="Revoke Alumni Status", style=discord.ButtonStyle.secondary, emoji="🎓")
            btn_alumni_revoke.callback = self._on_alumni_revoke_clicked
            self.add_item(btn_alumni_revoke)

        elif self.current_category == "tickets":
            btn_refresh_tickets = ui.Button(label="Refresh Tickets", style=discord.ButtonStyle.secondary, emoji="🔄")
            btn_refresh_tickets.callback = self._on_refresh_tickets
            self.add_item(btn_refresh_tickets)

        elif self.current_category == "backup":
            btn_create_backup = ui.Button(label="Create Backup Now", style=discord.ButtonStyle.success, emoji="💾")
            btn_create_backup.callback = self._on_create_backup_clicked
            self.add_item(btn_create_backup)

            btn_restore_settings = ui.Button(
                label="Restore Latest Settings", style=discord.ButtonStyle.secondary, emoji="🔄"
            )
            btn_restore_settings.callback = self._on_restore_settings_clicked
            self.add_item(btn_restore_settings)

        elif self.current_category == "logs":
            btn_archive_logs = ui.Button(
                label="Run 10-Day Archival (.tar.gz)", style=discord.ButtonStyle.success, emoji="🗜️"
            )
            btn_archive_logs.callback = self._on_archive_logs_clicked
            self.add_item(btn_archive_logs)

            btn_tail_logs = ui.Button(label="View Recent Log Lines", style=discord.ButtonStyle.secondary, emoji="📄")
            btn_tail_logs.callback = self._on_tail_logs_clicked
            self.add_item(btn_tail_logs)

        elif self.current_category == "panel":
            btn_deploy_here = ui.Button(
                label="Deploy to Current Channel", style=discord.ButtonStyle.success, emoji="🚀"
            )
            btn_deploy_here.callback = self._on_deploy_here_clicked
            self.add_item(btn_deploy_here)

            btn_deploy_pick = ui.Button(
                label="Deploy to Another Channel...", style=discord.ButtonStyle.secondary, emoji="📢"
            )
            btn_deploy_pick.callback = lambda i: self._show_channel_select(i, "panel_deploy")
            self.add_item(btn_deploy_pick)

        elif self.current_category == "updates":
            btn_check_up = ui.Button(label="Check Upstream Commits", style=discord.ButtonStyle.primary, emoji="🔄")
            btn_check_up.callback = self._on_check_updates_clicked
            self.add_item(btn_check_up)

            btn_resync = ui.Button(label="Resync Mutual Server Roles", style=discord.ButtonStyle.secondary, emoji="🔄")
            btn_resync.callback = self._on_resync_clicked
            self.add_item(btn_resync)

        elif self.current_category == "randomtag":
            btn_toggle = ui.Button(label="Toggle Enable/Disable", style=discord.ButtonStyle.primary, emoji="🔄")
            btn_toggle.callback = self._on_randomtag_toggle_clicked
            self.add_item(btn_toggle)

            btn_config = ui.Button(label="Configure Settings & Words", style=discord.ButtonStyle.secondary, emoji="⚙️")
            btn_config.callback = self._on_randomtag_config_clicked
            self.add_item(btn_config)

            btn_mode = ui.Button(label="Toggle Rotation Mode", style=discord.ButtonStyle.secondary, emoji="🔀")
            btn_mode.callback = self._on_randomtag_mode_clicked
            self.add_item(btn_mode)

        elif self.current_category == "uptime":
            btn_refresh_uptime = ui.Button(label="Refresh SLA Metrics", style=discord.ButtonStyle.primary, emoji="🔄")
            btn_refresh_uptime.callback = self._on_refresh_uptime_clicked
            self.add_item(btn_refresh_uptime)

    async def refresh_view(self, interaction: discord.Interaction) -> None:
        self._rebuild_components()
        embed = await self.build_current_embed(interaction.guild)
        await self.update_message(interaction, embed=embed)

    async def update_message(self, interaction: discord.Interaction, embed: discord.Embed) -> None:
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)
