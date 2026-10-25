"""Channel, role, email and SRC settings plus the gateway panel."""

from __future__ import annotations

import logging
from typing import Literal

import discord
from discord import app_commands

from tarveri.cogs.admin.groups import admin_group
from tarveri.config import (
    SRC_ROLE_NAMES,
)
from tarveri.utils import schedule_ttl_delete

logger = logging.getLogger("tarveri")


class AdminSettingsCommands:
    """Channel, role, email and SRC settings plus the gateway panel."""

    # ==========================================
    # ⚙️ 5. Consolidated Server Channel & Role Settings
    # ==========================================

    @admin_group.command(
        name="set_channel",
        description="Configure or reset welcome, help, or guest review channels for this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        channel_type="The type of channel to configure (welcome, help, or review)",
        channel="The text channel to set (leave blank to reset to auto-detect)",
    )
    async def set_channel(
        self,
        interaction: discord.Interaction,
        channel_type: Literal["welcome", "help", "review"],
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Consolidated channel configuration for welcome, help, and review channels."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        channel_id = channel.id if channel else None

        if channel_type == "welcome":
            await self.db.set_guild_welcome_channel(interaction.guild.id, channel_id)
            verif_cog = self.bot.get_cog("Verification")
            if verif_cog and hasattr(verif_cog, "invalidate_guild_cache"):
                verif_cog.invalidate_guild_cache(interaction.guild.id)
            desc = (
                f"Welcome channel set to {channel.mention}."
                if channel
                else "Welcome channel reset to **auto-detect** mode."
            )
        elif channel_type == "help":
            await self.db.set_guild_help_channel(interaction.guild.id, channel_id)
            verif_cog = self.bot.get_cog("Verification")
            if verif_cog and hasattr(verif_cog, "invalidate_guild_cache"):
                verif_cog.invalidate_guild_cache(interaction.guild.id)
            desc = (
                f"Help channel set to {channel.mention}." if channel else "Help channel reset to **auto-detect** mode."
            )
        elif channel_type == "review":
            await self.db.set_guild_review_channel(interaction.guild.id, channel_id)
            desc = (
                f"Guest review channel set to {channel.mention}."
                if channel
                else "Guest review channel reset to **auto-detect** mode."
            )

        await self.db.log(
            "INFO",
            f"CONFIG_{channel_type.upper()}_CHANNEL",
            f"Admin {interaction.user} set {channel_type} channel to '{channel.name if channel else 'Auto-detect'}' ({channel_id})",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        await interaction.followup.send(f"✅ {desc}", ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @admin_group.command(
        name="set_role",
        description="Configure or reset custom guest role or reviewer/admin role.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        role_type="The role setting to configure (guest or admin)",
        role="The Discord role (for admin role, or leave blank to reset)",
        role_name="Custom role name string (for guest role, e.g. 'Guest (Approved)')",
    )
    async def set_role(
        self,
        interaction: discord.Interaction,
        role_type: Literal["guest", "admin"],
        role: discord.Role | None = None,
        role_name: str | None = None,
    ) -> None:
        """Consolidated role configuration for guest and admin reviewer roles."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        if role_type == "guest":
            target_name = role_name.strip() if role_name else (role.name if role else "Guest")
            await self.db.set_guild_guest_role(interaction.guild.id, target_name)
            desc = f"Guest role name set to **{target_name}**."
            log_key = "CONFIG_GUEST_ROLE"
            log_val = target_name
        else:  # admin
            target_name = role.name if role else (role_name.strip() if role_name else None)
            await self.db.set_guild_admin_role(interaction.guild.id, target_name)
            desc = (
                f"Admin / Reviewer role set to {role.mention if role else target_name}."
                if target_name
                else "Admin / Reviewer role reset to **auto-detect** mode."
            )
            log_key = "CONFIG_ADMIN_ROLE"
            log_val = target_name or "Auto-detect"

        await self.db.log(
            "INFO",
            log_key,
            f"Admin {interaction.user} set {role_type} role to '{log_val}'",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        await interaction.followup.send(f"✅ {desc}", ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    # Legacy individual helper aliases for direct backwards compatibility
    async def setwelcomec(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.set_channel(interaction, channel_type="welcome", channel=channel)

    async def sethelpc(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        await self.set_channel(interaction, channel_type="help", channel=channel)

    async def setreviewchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        await self.set_channel(interaction, channel_type="review", channel=channel)

    async def setguestrole(self, interaction: discord.Interaction, role_name: str | None = None) -> None:
        await self.set_role(interaction, role_type="guest", role_name=role_name)

    async def setadminrole(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        await self.set_role(interaction, role_type="admin", role=role)

    @admin_group.command(
        name="email_verification",
        description="Configure whether student email OTP verification is required in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        enabled="True to mandate student email OTP (Opt-In), False to make it optional (Opt-Out).",
    )
    async def email_verification(self, interaction: discord.Interaction, enabled: bool) -> None:
        """Sets the per-guild email verification requirement (opt-in / opt-out)."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used within a server.", ephemeral=True)
            return

        await self.db.set_guild_email_verification(interaction.guild.id, enabled)
        await self.db.log(
            "INFO",
            "CONFIG_EMAIL_VERIFICATION",
            f"Email verification requirement set to {enabled} by {interaction.user}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        mode_str = "**MANDATORY (Opted In)**" if enabled else "**OPTIONAL (Opted Out)**"
        await interaction.response.send_message(
            f"✅ Email verification requirement for **{interaction.guild.name}** is now {mode_str}.",
            ephemeral=True,
        )
        schedule_ttl_delete(interaction, delay=60.0)

    @admin_group.command(
        name="email_enforcement",
        description="Toggle retroactive role stripping for non-email-verified members during self-healing.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        enabled="True to retroactively strip roles from non-email-verified members, False to preserve existing roles (Default).",
    )
    async def email_enforcement(self, interaction: discord.Interaction, enabled: bool) -> None:
        """Sets the retroactive email role enforcement toggle for the server."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ This command must be used within a server.", ephemeral=True)
            return

        await self.db.set_guild_email_enforcement(interaction.guild.id, enabled)
        await self.db.log(
            "INFO",
            "CONFIG_EMAIL_ENFORCEMENT",
            f"Email role enforcement set to {enabled} by {interaction.user}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        mode_str = (
            "🔴 **ENFORCED (Retroactive role stripping active during self-healing)**"
            if enabled
            else "🟢 **DISABLED (Existing verified roles are safely preserved)**"
        )
        await interaction.response.send_message(
            f"✅ Email role enforcement for **{interaction.guild.name}** is now {mode_str}.",
            ephemeral=True,
        )
        schedule_ttl_delete(interaction, delay=60.0)

    @admin_group.command(
        name="src",
        description="Configure, enable, disable, or remove faculty SRC roles in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        action="Action to perform: status (check state), enable (opt-in & restore roles), disable (opt-out), or remove (delete roles).",
    )
    async def src_command(
        self,
        interaction: discord.Interaction,
        action: Literal["status", "enable", "disable", "remove"] = "status",
    ) -> None:
        """Manages faculty SRC roles and server opt-in policy."""
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

        if action == "status":
            is_enabled = await self.db.is_guild_src_roles_enabled(guild.id)
            existing_roles = [r for r in guild.roles if r.name in SRC_ROLE_NAMES]
            embed = discord.Embed(
                title=f"🏛️ SRC Roles Configuration — {guild.name}",
                color=discord.Color.blue(),
            )
            status_text = (
                "🟢 **ENABLED** (Roles are auto-managed and restored during self-healing)"
                if is_enabled
                else "⚪ **DISABLED** (Skipped for this server)"
            )
            embed.add_field(name="Policy Status", value=status_text, inline=False)
            embed.add_field(
                name="Existing SRC Roles on Server",
                value=(
                    f"Found **{len(existing_roles)}/{len(SRC_ROLE_NAMES)}** faculty SRC roles on this server."
                    if existing_roles
                    else "*No faculty SRC roles currently exist on this server.*"
                ),
                inline=False,
            )
            embed.set_footer(text="Use '/admin src enable' to turn on, or '/admin src remove' to delete them.")
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif action == "enable":
            await self.db.set_guild_src_roles_enabled(guild.id, True)
            src_stats = await self.service.restore_src_roles(guild, force=True)
            await self.db.log(
                "INFO",
                "CONFIG_SRC_ROLES",
                f"SRC role management enabled by {interaction.user} (Created: {src_stats['created']}, Existing: {src_stats['existing']})",
                guild=guild,
                user_id=interaction.user.id,
            )
            embed = discord.Embed(
                title=f"✅ SRC Role Management Enabled — {guild.name}",
                description="Faculty SRC roles are now **enabled** and will be maintained on this server.",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Restoration Summary",
                value=f"• Created: **{src_stats['created']}** missing role(s)\n• Already Existing: **{src_stats['existing']}** role(s)\n• Failed: **{src_stats['failed']}**",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif action == "disable":
            await self.db.set_guild_src_roles_enabled(guild.id, False)
            await self.db.log(
                "INFO",
                "CONFIG_SRC_ROLES",
                f"SRC role management disabled by {interaction.user}",
                guild=guild,
                user_id=interaction.user.id,
            )
            embed = discord.Embed(
                title=f"⚪ SRC Role Management Disabled — {guild.name}",
                description=(
                    "SRC roles will **no longer be auto-created or restored** during bot restarts or diagnostics.\n"
                    "*(Note: Existing roles were left untouched. Use `/admin src remove` if you wish to delete them).*"
                ),
                color=discord.Color.light_grey(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif action == "remove":
            stats = await self.service.remove_src_roles(guild)
            embed = discord.Embed(
                title=f"🗑️ Faculty SRC Roles Removed — {guild.name}",
                description=f"Successfully deleted **{stats['deleted']}** faculty SRC role(s) from this server and disabled SRC role management.",
                color=discord.Color.red(),
            )
            if stats["failed"] > 0:
                embed.add_field(
                    name="⚠️ Failures",
                    value=f"{stats['failed']} role(s) could not be deleted (ensure bot's role is positioned above them in Server Settings > Roles).",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

        schedule_ttl_delete(interaction, delay=60.0)

    # ==========================================
    # 🚀 6. Verification Gateway Panel Deployer
    # ==========================================

    @admin_group.command(
        name="panel",
        description="Deploy the persistent 3-button verification gateway panel.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(channel="Target channel (defaults to current channel)")
    async def panel(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
        """Posts the persistent verification gateway panel."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        target_ch = channel or interaction.channel
        if not isinstance(target_ch, discord.TextChannel):
            await interaction.response.send_message("❌ Target must be a text channel.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        from tarveri.cogs.guest_cog import VerificationGatewayView, build_gateway_panel_embed

        guest_service = getattr(self.bot, "guest_service", None)
        if not guest_service:
            from tarveri.services.guest_service import GuestService

            guest_service = GuestService(
                bot=self.bot,
                db=self.db,
                rate_limiter=self.rate_limiter,
                admin_role_name=self.admin_role_name,
            )

        email_required = (
            await self.db.is_guild_email_verification_enabled(interaction.guild.id) if interaction.guild else False
        )
        guild_name = interaction.guild.name if interaction.guild else "the Server"
        embed = build_gateway_panel_embed(guild_name=guild_name, require_email=email_required)

        view = VerificationGatewayView(self.service, guest_service)
        try:
            await target_ch.send(embed=embed, view=view)
            await interaction.followup.send(
                f"✅ Verification gateway panel posted to {target_ch.mention}!", ephemeral=True
            )
        except (discord.HTTPException, discord.Forbidden) as e:
            await interaction.followup.send(f"❌ Failed to send gateway panel: {e}", ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    # Legacy alias
    async def send_gateway_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        await self.panel(interaction, channel=channel)
