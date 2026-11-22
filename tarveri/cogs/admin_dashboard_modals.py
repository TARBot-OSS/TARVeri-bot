"""Modals for the admin dashboard."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import ui

from tarveri.config import CAMPUS_ROLES, STUDY_LEVEL_ROLES
from tarveri.runtime_settings import RUNTIME_SETTINGS, SETTINGS_BY_KEY, parse_runtime_form
from tarveri.services.student_search import StudentNameMatch, search_students_by_name
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


class StudentSearchResultSelect(ui.Select):
    """Opens the full lookup record for one of the name search results."""

    def __init__(self, dashboard_view: AdminDashboardView, matches: list[StudentNameMatch]) -> None:
        options = [
            discord.SelectOption(
                label=m.name.title()[:100],
                value=str(m.discord_user_id),
                description=f"{m.faculty_code or '?'} · {CAMPUS_ROLES.get(m.campus_code or '', '?')} · {int(m.score * 100)}% match"[
                    :100
                ],
            )
            for m in matches
        ]
        super().__init__(placeholder="Open a student's full record...", options=options, min_values=1, max_values=1)
        self.dashboard_view = dashboard_view

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        embed = await self.dashboard_view.build_user_details_embed(int(self.values[0]), interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)


class StudentNameSearchModal(ui.Modal, title="🔎 Find Student by Name"):
    name_query = ui.TextInput(
        label="Student name",
        placeholder="e.g. Tan Wei Ming, weiming tan, or tanweiming",
        required=True,
        min_length=2,
        max_length=64,
    )

    def __init__(self, cog: AdminCog, dashboard_view: AdminDashboardView) -> None:
        super().__init__()
        self.cog = cog
        self.dashboard_view = dashboard_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("❌ This search only works inside a server.", ephemeral=True)
            return
        email_service = getattr(self.cog.bot, "email_service", None)
        if not email_service or not getattr(email_service.settings, "email_encryption_key", ""):
            await interaction.followup.send(
                "❌ Name search needs `TARVERI_EMAIL_ENCRYPTION_KEY`: names come from encrypted student emails.",
                ephemeral=True,
            )
            return

        query = self.name_query.value.strip()
        records = await self.cog.db.get_email_verified_students()
        # Only this server's members: admins of one server cannot browse students of another.
        member_ids = {m.id for m in interaction.guild.members}
        matches = search_students_by_name(query, records, email_service.decrypt_student_email, member_ids)

        await self.cog.db.log(
            "INFO",
            "ADMIN_STUDENT_NAME_SEARCH",
            f"Admin {interaction.user} searched students by name '{query}' ({len(matches)} match(es))",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        if not matches:
            await interaction.followup.send(
                f"🔎 No email-verified member matches **{discord.utils.escape_markdown(query)}**. "
                "Only students who verified with their institutional email have a name on file.",
                ephemeral=True,
            )
            return

        lines = []
        for i, m in enumerate(matches, 1):
            level = STUDY_LEVEL_ROLES.get(m.level_code or "", "?")
            campus = CAMPUS_ROLES.get(m.campus_code or "", "?")
            alumni = " · 🎓 Alumni" if m.is_alumni else ""
            lines.append(
                f"**{i}. {m.name.title()}** — <@{m.discord_user_id}> (`{m.discord_user_id}`)\n"
                f"   {m.faculty_code or '?'} · {campus} · {level}{alumni} · {int(m.score * 100)}% match"
            )
        embed = discord.Embed(
            title=f"🔎 Students matching “{query}”",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Names come from the student's institutional email. Pick one below for the full record.")
        view = ui.View(timeout=300)
        view.add_item(StudentSearchResultSelect(self.dashboard_view, matches))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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
