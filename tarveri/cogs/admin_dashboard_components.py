"""Select components for the admin dashboard."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import ui

if TYPE_CHECKING:
    from tarveri.cogs.admin_cog import AdminCog
    from tarveri.cogs.admin_dashboard import AdminDashboardView

logger = logging.getLogger("tarveri")


class ChannelSelectComponent(ui.ChannelSelect):
    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView, config_type: str) -> None:
        super().__init__(
            placeholder=f"Select channel for {config_type.title()}...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            custom_id=f"admin_select_ch_{config_type}",
        )
        self.cog = cog
        self.dashboard_view = dashboard_view
        self.config_type = config_type

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not self.values:
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        selected_ch = self.values[0]
        channel_id = selected_ch.id

        if self.config_type == "welcome":
            await self.cog.db.set_guild_welcome_channel(interaction.guild.id, channel_id)
            verif_cog = self.cog.bot.get_cog("Verification")
            if verif_cog and hasattr(verif_cog, "invalidate_guild_cache"):
                verif_cog.invalidate_guild_cache(interaction.guild.id)
        elif self.config_type == "help":
            await self.cog.db.set_guild_help_channel(interaction.guild.id, channel_id)
            verif_cog = self.cog.bot.get_cog("Verification")
            if verif_cog and hasattr(verif_cog, "invalidate_guild_cache"):
                verif_cog.invalidate_guild_cache(interaction.guild.id)
        elif self.config_type == "review":
            await self.cog.db.set_guild_review_channel(interaction.guild.id, channel_id)
        elif self.config_type == "panel_deploy":
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
                await self.cog.db.is_guild_email_verification_enabled(interaction.guild.id)
                if interaction.guild
                else False
            )
            guild_name = interaction.guild.name if interaction.guild else "the Server"
            embed = build_gateway_panel_embed(guild_name=guild_name, require_email=email_required)
            gateway_view = VerificationGatewayView(self.cog.service, guest_service)

            target_ch = interaction.guild.get_channel(channel_id)
            if isinstance(target_ch, discord.TextChannel):
                await target_ch.send(embed=embed, view=gateway_view)
                await interaction.followup.send(
                    f"✅ **Persistent Verification Gateway Panel deployed to {target_ch.mention}!**",
                    ephemeral=True,
                )
                return

        await self.cog.db.log(
            "INFO",
            f"CONFIG_{self.config_type.upper()}_CHANNEL",
            f"Admin {interaction.user} set {self.config_type} channel to {selected_ch.name} ({channel_id})",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        self.dashboard_view._rebuild_components()
        embed = await self.dashboard_view.build_config_embed(interaction.guild)
        await self.dashboard_view.update_message(interaction, embed=embed)


class RoleSelectComponent(ui.RoleSelect):
    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__(
            placeholder="Select Admin / Reviewer Role...",
            min_values=1,
            max_values=1,
            custom_id="admin_select_admin_role",
        )
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not self.values:
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        selected_role = self.values[0]
        await self.cog.db.set_guild_admin_role(interaction.guild.id, selected_role.name)

        await self.cog.db.log(
            "INFO",
            "CONFIG_ADMIN_ROLE",
            f"Admin {interaction.user} set admin/reviewer role to '{selected_role.name}'",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        self.dashboard_view._rebuild_components()
        embed = await self.dashboard_view.build_config_embed(interaction.guild)
        await self.dashboard_view.update_message(interaction, embed=embed)


class AdminCategorySelect(ui.Select):
    def __init__(self, dashboard_view: AdminDashboardView) -> None:
        options = [
            discord.SelectOption(
                label="Overview & Statistics",
                value="overview",
                description="View verification metrics, faculty breakdown, and counts.",
                emoji="📊",
                default=dashboard_view.current_category == "overview",
            ),
            discord.SelectOption(
                label="Server Configuration",
                value="config",
                description="Configure welcome, help, review channels, and roles.",
                emoji="⚙️",
                default=dashboard_view.current_category == "config",
            ),
            discord.SelectOption(
                label="Diagnostics & Auto-Healing",
                value="diagnose",
                description="Check permissions, hierarchy, restore missing/SRC roles.",
                emoji="🩺",
                default=dashboard_view.current_category == "diagnose",
            ),
            discord.SelectOption(
                label="Member Moderation",
                value="moderation",
                description="Unverify student IDs and revoke Alumni status.",
                emoji="👥",
                default=dashboard_view.current_category == "moderation",
            ),
            discord.SelectOption(
                label="Guest Review Tickets",
                value="tickets",
                description="Inspect recent guest review tickets and verdicts.",
                emoji="🎟️",
                default=dashboard_view.current_category == "tickets",
            ),
            discord.SelectOption(
                label="Database Backups",
                value="backup",
                description="Manage SQLite database snapshots and restores.",
                emoji="💾",
                default=dashboard_view.current_category == "backup",
            ),
            discord.SelectOption(
                label="Logs & Archives",
                value="logs",
                description="Inspect daily log files and 10-day .tar.gz archives.",
                emoji="📋",
                default=dashboard_view.current_category == "logs",
            ),
            discord.SelectOption(
                label="Deploy Gateway Panel",
                value="panel",
                description="Post persistent 3-button verification panel to a channel.",
                emoji="🚀",
                default=dashboard_view.current_category == "panel",
            ),
            discord.SelectOption(
                label="Updates & Role Resync",
                value="updates",
                description="Check upstream git commits and force role resync.",
                emoji="🔄",
                default=dashboard_view.current_category == "updates",
            ),
            discord.SelectOption(
                label="Random User Tagging",
                value="randomtag",
                description="Configure periodic, randomized mentions in #general.",
                emoji="🎲",
                default=dashboard_view.current_category == "randomtag",
            ),
            discord.SelectOption(
                label="Uptime & SLA Tracking",
                value="uptime",
                description="View continuous uptime, downtime history, and SLA availability scores.",
                emoji="⏱️",
                default=dashboard_view.current_category == "uptime",
            ),
        ]
        super().__init__(
            placeholder="Select Control Center Category...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="admin_dashboard_category_select",
        )
        self.dashboard_view = dashboard_view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.dashboard_view.current_category = self.values[0]
        await self.dashboard_view.refresh_view(interaction)
