"""TARClub society pairing commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from tarveri.cogs.admin.groups import society_bridge_group
from tarveri.config import (
    generate_society_pairing_token,
)
from tarveri.utils import schedule_ttl_delete

logger = logging.getLogger("tarveri")


class AdminSocietyBridgeCommands:
    """TARClub society pairing commands."""

    # ==========================================
    # 🏛️ 12. TARClub Cross-Bot Integration
    # ==========================================

    @society_bridge_group.command(
        name="pair",
        description="Generate a secure cross-bot pairing token for a TARClub society server.",
    )
    @app_commands.describe(
        society_guild_id="The Discord Server ID of the society server",
        notes="Optional club name or reference notes",
    )
    @app_commands.default_permissions(administrator=True)
    async def pair_society(
        self,
        interaction: discord.Interaction,
        society_guild_id: str,
        notes: str | None = None,
    ) -> None:
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not society_guild_id.strip().isdigit():
            await interaction.response.send_message(
                "❌ Invalid `society_guild_id`. Please provide a numeric Discord server ID.",
                ephemeral=True,
            )
            return

        target_id = int(society_guild_id.strip())
        await interaction.response.defer(ephemeral=True)

        try:
            token, token_hash = generate_society_pairing_token(target_id)
        except RuntimeError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return
        await self.db.create_society_pairing(
            society_guild_id=target_id,
            token_hash=token_hash,
            paired_by=interaction.user.id,
            notes=notes,
        )
        await self.db.log(
            "INFO",
            "SOCIETY_PAIR_ISSUED",
            f"Pairing token issued for society guild {target_id} (notes: {notes or 'none'})",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        embed = discord.Embed(
            title="🤝 TARClub Society Pairing Token Generated",
            description=(
                f"**Target Society Server ID:** `{target_id}`\n"
                f"**Notes:** {notes or '*None*'}\n\n"
                f"🔑 **Pairing Token:**\n```\n{token}\n```\n"
                "**Instructions for Society Server Administrator:**\n"
                "In the society server, run:\n"
                f"`/integrate-tarveri link token:{token}`\n\n"
                "*(This token securely links the society server to TARVeri).* "
            ),
            color=0x00E676,
        )
        embed.set_footer(text="TARVeri & TARClub Integration Bridge")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @society_bridge_group.command(
        name="list",
        description="List all paired TARClub society servers and their link status.",
    )
    @app_commands.default_permissions(administrator=True)
    async def list_societies(self, interaction: discord.Interaction) -> None:
        if not self._check_admin(interaction):
            await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        paired = await self.db.list_paired_societies()

        if not paired:
            await interaction.followup.send(
                "ℹ️ No society servers paired yet. Use `/society_bridge pair` to generate a token.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🏛️ Paired TARClub Societies",
            description=f"Total registered society bridges: **{len(paired)}**\n",
            color=0x1E88E5,
        )
        for s in paired:
            status = "🟢 Active" if s["is_active"] else "🔴 Inactive"
            notes = f" • *{s['notes']}*" if s.get("notes") else ""
            embed.add_field(
                name=f"Guild ID: {s['society_guild_id']}",
                value=f"Status: {status}{notes}\nPaired: `{s['paired_at']}`",
                inline=False,
            )
        embed.set_footer(text="TARVeri & TARClub Cross-Bot Ecosystem")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @society_bridge_group.command(
        name="unpair",
        description="Revoke pairing with a TARClub society server.",
    )
    @app_commands.describe(society_guild_id="The Discord Server ID to unpair")
    @app_commands.default_permissions(administrator=True)
    async def unpair_society(
        self,
        interaction: discord.Interaction,
        society_guild_id: str,
    ) -> None:
        if not self._check_admin(interaction):
            await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
            return

        if not society_guild_id.strip().isdigit():
            await interaction.response.send_message("❌ Invalid Server ID.", ephemeral=True)
            return

        target_id = int(society_guild_id.strip())
        await interaction.response.defer(ephemeral=True)
        revoked = await self.db.revoke_society_pairing(target_id)
        await self.db.log(
            "INFO" if revoked else "WARNING",
            "SOCIETY_PAIR_REVOKED" if revoked else "SOCIETY_PAIR_REVOKE_NOOP",
            f"Pairing for society guild {target_id} {'revoked' if revoked else 'was not active, nothing revoked'}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        if revoked:
            await interaction.followup.send(
                f"✅ Successfully revoked pairing for society guild `{target_id}`.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"⚠️ Society guild `{target_id}` was not paired or already inactive.", ephemeral=True
            )
