"""Modals for the admin dashboard."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import ui

from tarveri.runtime_settings import RUNTIME_SETTINGS, SETTINGS_BY_KEY, parse_runtime_form
from tarveri.utils import schedule_ttl_delete

if TYPE_CHECKING:
    from tarveri.cogs.admin_cog import AdminCog
    from tarveri.cogs.admin_dashboard import AdminDashboardView

logger = logging.getLogger("tarveri")


def _extract_user_id(raw_str: str) -> int | None:
    """Extracts a numeric user ID from a raw string or mention (<@123456789>)."""
    raw_str = raw_str.strip()
    match = re.search(r"(\d{15,22})", raw_str)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


class UnverifyModal(ui.Modal, title="❌ Unverify Student"):
    user_input = ui.TextInput(
        label="Student User ID or Mention",
        placeholder="e.g. 123456789012345678 or @student",
        required=True,
        max_length=64,
    )
    reason_input = ui.TextInput(
        label="Reason for Unlinking Verification",
        placeholder="e.g. Identity correction, student withdrawal",
        required=False,
        max_length=256,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = _extract_user_id(self.user_input.value)
        if not user_id:
            await interaction.followup.send("❌ Invalid User ID or mention provided.", ephemeral=True)
            return

        reason = self.reason_input.value.strip() or "Unverified via Admin Dashboard"
        res = await self.cog.service.unverify_member(
            user_id=user_id,
            admin=interaction.user,
            current_guild=interaction.guild,
            reason=reason,
        )

        if not res.get("success"):
            await interaction.followup.send(
                f"ℹ️ User with ID `{user_id}` is not currently verified in the database.", ephemeral=True
            )
            return

        roles_removed = res.get("roles_removed", [])
        await interaction.followup.send(
            f"✅ **Successfully unverified user ID `{user_id}`**.\n"
            f"• Reason: *{reason}*\n"
            f"• Roles removed in {len(roles_removed)} server(s): {', '.join(roles_removed) if roles_removed else 'None'}",
            ephemeral=True,
        )
        schedule_ttl_delete(interaction, delay=60.0)


class AlumniRevokeModal(ui.Modal, title="🎓 Revoke Alumni Status"):
    user_input = ui.TextInput(
        label="Alumni User ID or Mention",
        placeholder="e.g. 123456789012345678 or @alumni",
        required=True,
        max_length=64,
    )
    reason_input = ui.TextInput(
        label="Reason for Revocation",
        placeholder="e.g. Ineligible claim, incorrect graduation year",
        required=False,
        max_length=256,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = _extract_user_id(self.user_input.value)
        if not user_id:
            await interaction.followup.send("❌ Invalid User ID or mention provided.", ephemeral=True)
            return

        target_member = None
        if interaction.guild:
            target_member = interaction.guild.get_member(user_id)
        if not target_member:
            target_member = discord.Object(id=user_id)

        reason = self.reason_input.value.strip() or "Revoked via Admin Dashboard"
        res = await self.cog.service.revoke_alumni_status(
            target_user=target_member,
            admin=interaction.user,
            current_guild=interaction.guild,
            reason=reason,
        )

        if not res.get("success"):
            await interaction.followup.send(
                f"❌ {res.get('message', 'Failed to revoke alumni status.')}", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ **Successfully revoked Alumni status for user ID `{user_id}`**.\n"
            f"• Removed `TARUMT Alumni` role across **{res.get('roles_removed_count', 0)}** mutual server(s).\n"
            f"• Reason: *{reason}*",
            ephemeral=True,
        )
        schedule_ttl_delete(interaction, delay=60.0)


class UserLookupModal(ui.Modal, title="🔍 Member & Verification Lookup"):
    user_input = ui.TextInput(
        label="User ID or Mention",
        placeholder="e.g. 123456789012345678 or @member",
        required=True,
        max_length=64,
    )

    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = _extract_user_id(self.user_input.value)
        if not user_id:
            await interaction.followup.send("❌ Invalid User ID or mention provided.", ephemeral=True)
            return

        embed = await self.dashboard_view.build_user_details_embed(user_id, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)


class GuestRoleModal(ui.Modal, title="⚙️ Configure Guest Role Name"):
    role_name_input = ui.TextInput(
        label="Guest Role Name",
        placeholder="e.g. Guest (Approved) (leave empty to reset to 'Guest')",
        required=False,
        max_length=100,
    )

    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Command must be used in a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        role_name = self.role_name_input.value.strip() or "Guest"
        await self.cog.db.set_guild_guest_role(interaction.guild.id, role_name)

        await self.cog.db.log(
            "INFO",
            "CONFIG_GUEST_ROLE",
            f"Admin {interaction.user} set guest role for '{interaction.guild.name}' to '{role_name}'",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        embed = await self.dashboard_view.build_config_embed(interaction.guild)
        await self.dashboard_view.update_message(interaction, embed=embed)


class RuntimeSettingsModal(ui.Modal, title="🛡️ Join Protection & Audit Tuning"):
    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view
        self.inputs: dict[str, ui.TextInput] = {}
        for setting in RUNTIME_SETTINGS:
            text_input = ui.TextInput(
                label=setting.label,
                default=f"{self.cog.db.runtime_settings[setting.key]:g}",
                max_length=10,
            )
            self.inputs[setting.key] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values, errors = parse_runtime_form({key: item.value for key, item in self.inputs.items()})
        if errors:
            await interaction.response.send_message(
                "❌ " + "\n❌ ".join(errors) + "\nNothing was saved.", ephemeral=True
            )
            return

        for key, value in values.items():
            await self.cog.db.set_runtime_setting(key, value, updated_by=interaction.user.id)
        await self.cog.db.log(
            "INFO",
            "CONFIG_RUNTIME",
            f"Admin {interaction.user} updated runtime settings: {values}",
            user_id=interaction.user.id,
        )

        summary = "\n".join(f"• {SETTINGS_BY_KEY[key].label}: `{value:g}`" for key, value in values.items())
        await interaction.response.send_message(f"✅ Saved and applied immediately:\n{summary}", ephemeral=True)
