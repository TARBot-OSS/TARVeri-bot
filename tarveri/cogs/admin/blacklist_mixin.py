"""Guild blacklist commands for users, student IDs and emails."""

from __future__ import annotations

import logging
from typing import Literal

import discord
from discord import app_commands

from tarveri.cogs.admin.groups import blacklist_group
from tarveri.utils import schedule_ttl_delete

logger = logging.getLogger("tarveri")


class AdminBlacklistCommands:
    """Guild blacklist commands for users, student IDs and emails."""

    @blacklist_group.command(
        name="user",
        description="Blacklist a Discord user from verifying or holding verified roles in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="The Discord user to blacklist",
        reason="Reason for blacklisting this user",
    )
    async def blacklist_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str | None = None,
    ) -> None:
        """Blacklists a Discord user in this server."""
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
        _, message = await self.service.blacklist_target(
            guild=interaction.guild,
            target_type="USER",
            raw_value=str(user.id),
            reason=reason,
            admin=interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @blacklist_group.command(
        name="student_id",
        description="Blacklist a Student ID from verifying in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        student_id="The Student ID to blacklist (e.g. 23WMD09867)",
        reason="Reason for blacklisting this Student ID",
    )
    async def blacklist_student_id(
        self,
        interaction: discord.Interaction,
        student_id: str,
        reason: str | None = None,
    ) -> None:
        """Blacklists a Student ID in this server."""
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
        _, message = await self.service.blacklist_target(
            guild=interaction.guild,
            target_type="STUDENT_ID",
            raw_value=student_id,
            reason=reason,
            admin=interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @blacklist_group.command(
        name="email",
        description="Blacklist an institutional student email from verifying in this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        email="The institutional email address to blacklist (e.g. name-wm24@student.tarc.edu.my)",
        reason="Reason for blacklisting this email",
    )
    async def blacklist_email(
        self,
        interaction: discord.Interaction,
        email: str,
        reason: str | None = None,
    ) -> None:
        """Blacklists an institutional student email in this server."""
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
        _, message = await self.service.blacklist_target(
            guild=interaction.guild,
            target_type="EMAIL",
            raw_value=email,
            reason=reason,
            admin=interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @blacklist_group.command(
        name="remove",
        description="Remove a target (User ID, Student ID, or Email) from this server's blacklist.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        target_type="The type of target to remove",
        target="The Discord User ID, Student ID, or Email to unblacklist",
    )
    async def blacklist_remove(
        self,
        interaction: discord.Interaction,
        target_type: Literal["USER", "STUDENT_ID", "EMAIL"],
        target: str,
    ) -> None:
        """Removes a target from this server's blacklist."""
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
        _, message = await self.service.unblacklist_target(
            guild=interaction.guild,
            target_type=target_type,
            raw_value=target,
            admin=interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @blacklist_group.command(
        name="list",
        description="View blacklisted entries for this server.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        target_type="Filter by target type (USER, STUDENT_ID, EMAIL, or ALL)",
        page="Page number to view (default: 1)",
    )
    async def blacklist_list(
        self,
        interaction: discord.Interaction,
        target_type: Literal["ALL", "USER", "STUDENT_ID", "EMAIL"] = "ALL",
        page: int = 1,
    ) -> None:
        """Lists blacklist entries for this server."""
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
        query_type = None if target_type == "ALL" else target_type
        total = await self.db.count_guild_blacklist(interaction.guild.id, target_type=query_type)
        if total == 0:
            type_suffix = f" matching type `{target_type}`" if target_type != "ALL" else ""
            await interaction.followup.send(
                f"ℹ️ No blacklist entries found for **{interaction.guild.name}**{type_suffix}.",
                ephemeral=True,
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        entries = await self.db.get_guild_blacklist(
            interaction.guild.id,
            target_type=query_type,
            limit=per_page,
            offset=offset,
        )

        embed = discord.Embed(
            title=f"🚫 Guild Blacklist • {interaction.guild.name}",
            description=f"Showing **{len(entries)}** of **{total}** blacklisted entry/entries (Page {page}/{total_pages}).",
            color=discord.Color.red(),
        )

        for entry in entries:
            t_type = entry["target_type"]
            mask = entry["display_mask"] or entry["target_value"]
            reason = entry["reason"] or "No reason specified"
            by_user = f"<@{entry['blacklisted_by']}>" if entry["blacklisted_by"] else "Admin"
            created = entry["created_at"]
            embed.add_field(
                name=f"[{t_type}] {mask}",
                value=f"**Reason:** {reason}\n**Added By:** {by_user} • **Date:** `{created}`",
                inline=False,
            )

        embed.set_footer(text=f"TARVeri Blacklist • Page {page}/{total_pages}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=90.0)

    @blacklist_group.command(
        name="clear",
        description="Clear all blacklist entries for this server.",
    )
    @app_commands.default_permissions(administrator=True)
    async def blacklist_clear(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Clears all blacklist entries for this server."""
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
        cleared_count = await self.db.clear_guild_blacklist(interaction.guild.id)
        await self.db.log(
            "WARNING",
            "BLACKLIST_CLEARED",
            f"Admin {interaction.user} cleared all {cleared_count} blacklist entries in '{interaction.guild.name}'",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )
        await interaction.followup.send(
            f"✅ Cleared **{cleared_count}** blacklist entries for **{interaction.guild.name}**.",
            ephemeral=True,
        )
        schedule_ttl_delete(interaction, delay=60.0)
