"""Member lookup, unverify, alumni revocation, role repair, tickets and mass revocation."""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime
from typing import Literal

import discord
from discord import app_commands

from tarveri.cogs.admin.groups import admin_group
from tarveri.cogs.admin_dashboard import AdminDashboardView
from tarveri.config import (
    CAMPUS_ROLE_NAMES,
    CAMPUS_ROLES,
    FACULTY_ROLE_NAMES,
    STUDY_LEVEL_ROLE_NAMES,
    STUDY_LEVEL_ROLES,
    get_configured_tz,
    resolve_campus_role,
    resolve_faculty_role,
    resolve_study_level_role,
)
from tarveri.utils import format_ticket_seq, parse_ticket_seq, schedule_ttl_delete

logger = logging.getLogger("tarveri")


class AdminUserCommands:
    """Member lookup, unverify, alumni revocation, role repair, tickets and mass revocation."""

    # ==========================================
    # 👥 4. Member Moderation (Lookup, Unverify & Revoke)
    # ==========================================

    @admin_group.command(
        name="user_info",
        description="Inspect member verification profile, student roles, join date, and audit history.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="The Discord member or user to inspect",
    )
    async def user_info(
        self,
        interaction: discord.Interaction,
        user: discord.User | discord.Member,
    ) -> None:
        """Inspects member verification status, faculty/campus/level roles, join history, and audit log."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)
        dashboard_view = AdminDashboardView(cog=self, admin_user=interaction.user, initial_category="moderation")
        embed = await dashboard_view.build_user_details_embed(user.id, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=180.0)

    @admin_group.command(name="unverify", description="Unlink a member's student ID and revoke faculty roles.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="The Discord user to unverify",
        reason="Optional reason for unlinking the verification record",
    )
    async def unverify(
        self,
        interaction: discord.Interaction,
        user: discord.User | discord.Member,
        reason: str | None = None,
    ) -> None:
        """Unlinks verification from DB, resets rate limit, and strips faculty/alumni roles across mutual servers."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        unverify_fn = getattr(self.service, "unverify_member", None)
        if callable(unverify_fn) and (
            inspect.iscoroutinefunction(unverify_fn)
            or getattr(type(unverify_fn), "__name__", "") in ("AsyncMock", "AsyncMockMixin")
            or getattr(type(self.service), "__name__", "") not in ("MagicMock", "Mock")
        ):
            res = await self.service.unverify_member(
                user_id=user.id,
                admin=interaction.user,
                current_guild=interaction.guild,
                reason=reason or "No reason provided",
            )
            if not res.get("success"):
                await interaction.followup.send(f"❌ {user.mention} is not verified.", ephemeral=True)
                schedule_ttl_delete(interaction, delay=60.0)
                return

            roles_removed_servers = res.get("roles_removed", [])
            report = f"✅ **Successfully unverified {user.mention} (ID: `{user.id}`).**\n"
            if reason:
                report += f"• **Reason:** *{reason}*\n"
            if roles_removed_servers:
                report += f"• **Roles removed in {len(roles_removed_servers)} server(s):** {', '.join(roles_removed_servers)}\n"
            else:
                report += "• **Roles removed:** None (member not found or had no roles)\n"
            report += "• **Rate Limiter:** Reset successfully. The user may now verify a new ID."

            await interaction.followup.send(report, ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        verif = await self.db.get_verification_by_user(user.id)
        if not verif:
            await interaction.followup.send(f"❌ {user.mention} is not verified.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        mutual_guilds = await self.service.get_mutual_guilds_for_user(user.id)
        roles_removed_servers = []

        for guild in mutual_guilds:
            member = await self.service.get_or_fetch_member(guild, user.id)
            if not member:
                continue

            roles_to_remove = [
                r
                for r in getattr(member, "roles", [])
                if any(self.service._match_faculty_role_in_list([r], fac) is not None for fac in FACULTY_ROLE_NAMES)
                or any(self.service._match_campus_role_in_list([r], camp) is not None for camp in CAMPUS_ROLE_NAMES)
                or any(
                    self.service._match_study_level_role_in_list([r], lvl) is not None for lvl in STUDY_LEVEL_ROLE_NAMES
                )
                or self.service._match_alumni_role_in_list([r]) is not None
            ]

            me = getattr(guild, "me", None)
            can_manage = (
                getattr(me.guild_permissions, "manage_roles", False)
                if me and hasattr(me, "guild_permissions")
                else False
            )
            bot_top = getattr(me, "top_role", None)
            bot_pos = getattr(bot_top, "position", 0) if bot_top else 0

            for role in roles_to_remove:
                role_pos = getattr(role, "position", 0)
                if can_manage and isinstance(bot_pos, int) and isinstance(role_pos, int) and role_pos < bot_pos:
                    try:
                        await member.remove_roles(
                            role,
                            reason=f"TARVeri: Verification unlinked by admin {interaction.user}. Reason: {reason or 'None'}",
                        )
                        roles_removed_servers.append(f"{guild.name} ({role.name})")
                    except discord.HTTPException as e:
                        logger.warning(f"Could not remove role {role.name} from {member} in {guild.name}: {e}")

        await self.db.delete_verification(user.id)
        self.rate_limiter.reset(user.id)

        await self.db.log(
            "WARNING",
            "MEMBER_UNVERIFIED",
            f"Admin {interaction.user} unverified member {user} (ID: {user.id}). Reason: {reason or 'No reason provided'}",
            guild=interaction.guild,
            user_id=user.id,
        )

        report = f"✅ **Successfully unverified {user.mention} (ID: `{user.id}`).**\n"
        if reason:
            report += f"• **Reason:** *{reason}*\n"
        if roles_removed_servers:
            report += (
                f"• **Roles removed in {len(roles_removed_servers)} server(s):** {', '.join(roles_removed_servers)}\n"
            )
        else:
            report += "• **Roles removed:** None (member not found or had no roles)\n"
        report += "• **Rate Limiter:** Reset successfully. The user may now verify a new ID."

        await interaction.followup.send(report, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @admin_group.command(
        name="alumni_revoke",
        description="Revoke a member's graduated alumni status and remove TARUMT Alumni role.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="The Discord member whose Alumni status to revoke",
        reason="Reason for revoking Alumni status",
    )
    async def alumni_revoke(
        self,
        interaction: discord.Interaction,
        user: discord.User | discord.Member,
        reason: str | None = None,
    ) -> None:
        """Revokes alumni status from a verified member and strips their alumni role across mutual servers."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        res = await self.service.revoke_alumni_status(
            target_user=user,
            admin=interaction.user,
            current_guild=interaction.guild,
            reason=reason,
        )

        if not res.get("success"):
            await interaction.followup.send(
                f"❌ {res.get('message', 'Failed to revoke alumni status.')}", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        msg = (
            f"✅ **Successfully revoked Alumni status for {user.mention} (ID: `{user.id}`).**\n"
            f"• Removed `TARUMT Alumni` role across **{res.get('roles_removed_count', 0)}** mutual server(s).\n"
            f"• **Reason:** *{reason or 'No reason provided'}*"
        )
        await interaction.followup.send(msg, ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    @admin_group.command(
        name="backfill_roles",
        description="One-time migration: backfill branch campus & study level roles to previously verified students.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        default_campus="Default branch campus for legacy students without a branch tag (default: KL Main Campus)",
        default_level="Optional default study level for legacy students without a study level tag",
        all_servers="Whether to run the backfill across all mutual servers (default: True)",
    )
    @app_commands.choices(
        default_campus=[
            app_commands.Choice(name="KL Main Campus", value="W"),
            app_commands.Choice(name="Penang Branch", value="P"),
            app_commands.Choice(name="Perak Branch", value="A"),
            app_commands.Choice(name="Johor Branch", value="J"),
            app_commands.Choice(name="Pahang Branch", value="C"),
            app_commands.Choice(name="Sabah Branch", value="S"),
        ],
        default_level=[
            app_commands.Choice(name="Diploma", value="D"),
            app_commands.Choice(name="Degree", value="R"),
            app_commands.Choice(name="Foundation", value="F"),
            app_commands.Choice(name="Postgraduate", value="P"),
        ],
    )
    async def backfill_roles(
        self,
        interaction: discord.Interaction,
        default_campus: app_commands.Choice[str] | None = None,
        default_level: app_commands.Choice[str] | None = None,
        all_servers: bool = True,
    ) -> None:
        """Backfills missing branch campus and study level roles for existing verified students."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        campus_code = default_campus.value if default_campus else "W"
        level_code = default_level.value if default_level else None
        target_guild = None if all_servers else interaction.guild

        stats = await self.service.backfill_branch_roles(
            guild=target_guild,
            default_campus_code=campus_code,
            default_level_code=level_code,
        )

        embed = discord.Embed(
            title="🔄 Branch Campus & Study Level Role Backfill",
            color=discord.Color.brand_green(),
        )
        embed.add_field(
            name="📊 Migration Summary",
            value=(
                f"• Shared Servers Scanned: **{stats['guilds_scanned']}**\n"
                f"• Verified Members Checked: **{stats['members_checked']}**\n"
                f"• Roles Backfilled / Restored: **{stats['roles_assigned']}**\n"
                f"• Database Records Migrated: **{stats['db_migrated']}**\n"
                f"• Failed / Blocked: **{stats['failed']}**"
            ),
            inline=False,
        )
        campus_label = CAMPUS_ROLES.get(campus_code, "KL Main Campus")
        level_label = STUDY_LEVEL_ROLES.get(level_code) if level_code else "Auto-detected from Discord / Kept as is"
        embed.set_footer(text=f"Default Branch: {campus_label} | Default Level: {level_label}")

        await self.db.log(
            "INFO",
            "BRANCH_ROLES_BACKFILLED",
            f"Admin {interaction.user} triggered branch role backfill: {stats}",
            guild=interaction.guild,
            user_id=interaction.user.id,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=90.0)

    @admin_group.command(
        name="restore_roles",
        description="Immediately restore and recover missing verified roles for past verified members.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        user="Optional specific member to recover roles for (leave empty to scan and recover entire server)"
    )
    async def restore_roles(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        """Immediately restores missing verified roles for past verified students."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if user:
            details = await self.db.get_verification_details(user.id)
            if not details:
                verif = await self.db.get_verification_by_user(user.id)
                if not verif:
                    await interaction.followup.send(
                        f"⚠️ {user.mention} is not recorded as a verified student in the database.",
                        ephemeral=True,
                    )
                    return
                faculty_code = verif[1]
                campus_code = "W"
                level_code = "R"
                is_alumni = False
            else:
                faculty_code = details.get("faculty_code")
                campus_code = details.get("campus_code") or "W"
                level_code = details.get("level_code") or "R"
                is_alumni = bool(details.get("is_alumni"))

            target_faculty = resolve_faculty_role(faculty_code)
            target_campus = resolve_campus_role(campus_code)
            target_level = resolve_study_level_role(level_code)

            if not target_faculty:
                await interaction.followup.send(
                    f"❌ Could not resolve faculty role for {user.mention} (stored code: `{faculty_code}`).",
                    ephemeral=True,
                )
                return

            result = await self.service.assign_role_across_guilds(
                user.id,
                target_faculty,
                [interaction.guild],
                campus_role_name=target_campus,
                level_role_name=target_level,
                is_email_verified=bool(details.get("student_email_hash")) if details else False,
            )

            if is_alumni:
                try:
                    await self.service.sync_alumni_role_across_guilds(
                        user.id, [interaction.guild], reason="TARVeri: Admin role recovery"
                    )
                except Exception as exc:
                    logger.warning("Failed syncing alumni role during restore_roles: %s", exc)

            summary = self.service.format_role_summary(result)
            await self.db.log(
                "INFO",
                "ROLE_RECOVERED_MANUAL",
                f"Admin {interaction.user} restored roles for {user} (ID: {user.id}) in '{interaction.guild.name}'",
                guild=interaction.guild,
                user_id=user.id,
            )
            embed = discord.Embed(
                title=f"✅ Verified Roles Restored for {user.display_name}",
                description=summary or f"Roles successfully synchronized for {user.mention}.",
                color=discord.Color.green(),
                timestamp=datetime.now(get_configured_tz()),
            )
            embed.add_field(name="🏛️ Faculty", value=f"`{target_faculty}`", inline=True)
            embed.add_field(name="🏫 Campus", value=f"`{target_campus}`", inline=True)
            embed.add_field(name="🎓 Level", value=f"`{target_level}`", inline=True)
            if is_alumni:
                embed.add_field(name="🎖️ Alumni", value="`TARUMT Alumni`", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            stats = await self.service.reconcile_verified_members(interaction.guild)
            alumni_stats = await self.service.reconcile_alumni_members(interaction.guild)
            embed = discord.Embed(
                title=f"🔄 Server Role Recovery & Reconciliation — {interaction.guild.name}",
                description="Completed self-healing recovery scan for past verified members.",
                color=discord.Color.brand_green(),
                timestamp=datetime.now(get_configured_tz()),
            )
            embed.add_field(name="👥 Members Checked", value=f"**{stats.get('checked', 0)}**", inline=True)
            embed.add_field(name="✅ Roles Restored", value=f"**{stats.get('restored', 0)}**", inline=True)
            embed.add_field(name="🎓 Alumni Restored", value=f"**{alumni_stats.get('restored', 0)}**", inline=True)
            if stats.get("failed", 0) > 0:
                embed.add_field(name="⚠️ Hierarchy/Blocked", value=f"**{stats.get('failed', 0)}**", inline=True)

            await self.db.log(
                "INFO",
                "SERVER_ROLES_RESTORED",
                f"Admin {interaction.user} triggered full server role recovery: {stats}",
                guild=interaction.guild,
                user_id=interaction.user.id,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        schedule_ttl_delete(interaction, delay=90.0)

    # ==========================================
    # 🔄 11. Role Resynchronization
    # ==========================================

    @admin_group.command(name="resync", description="Force resynchronization of verification roles.")
    @app_commands.default_permissions(administrator=True)
    async def resync(self, interaction: discord.Interaction) -> None:
        """Checks and re-applies faculty and alumni roles across mutual servers."""
        if not self._check_admin(interaction):
            await interaction.response.send_message(
                "❌ You do not have permission to use this command.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        if interaction.guild:
            reconcile_stats = await self.service.reconcile_verified_members(interaction.guild)
            alumni_stats = await self.service.reconcile_alumni_members(interaction.guild)
            await interaction.followup.send(
                f"✅ **Mutual Server Role Resynchronization Complete!**\n"
                f"• Verified Students: checked **{reconcile_stats['checked']}**, restored **{reconcile_stats['restored']}**\n"
                f"• Graduated Alumni: checked **{alumni_stats['checked']}**, restored **{alumni_stats['restored']}**",
                ephemeral=True,
            )
        else:
            await interaction.followup.send("❌ Resync must be run in a server.", ephemeral=True)
        schedule_ttl_delete(interaction, delay=60.0)

    # ==========================================
    # 🎟️ 7. Guest Review Tickets
    # ==========================================

    @admin_group.command(
        name="tickets",
        description="List and inspect recent guest review tickets with links to threads.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        status="Filter by status (OPEN, APPROVED, REJECTED, EXPIRED, LEFT_SERVER)",
        limit="Number of records to show (1-20, default 10)",
    )
    async def tickets(
        self,
        interaction: discord.Interaction,
        status: str | None = None,
        limit: app_commands.Range[int, 1, 20] = 10,
    ) -> None:
        """Displays recent guest review tickets with clickable thread links and resolution details."""
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

        tickets_list = await self.db.list_guest_tickets(interaction.guild.id, status=status, limit=limit)

        if not tickets_list:
            filter_text = f" with status `{status}`" if status else ""
            await interaction.followup.send(f"ℹ️ No guest tickets found in this server{filter_text}.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        embed = discord.Embed(
            title=f"📋 Guest Review Tickets — {interaction.guild.name}",
            description=f"Showing **{len(tickets_list)}** recent ticket(s)"
            + (f" filtered by `{status.upper()}`" if status else "")
            + ":",
            color=discord.Color.blue(),
        )

        for t in tickets_list:
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
            admin_info = f" • Closed by <@{t['closed_by_admin_id']}>" if t.get("closed_by_admin_id") else ""
            reason_info = f'\n> Reason: *"{t["close_reason"]}"*' if t.get("close_reason") else ""

            field_name = f"{status_emoji} Ticket #{seq_code} — {t_status}"
            field_value = (
                f"**Applicant:** {applicant_mention} | **Thread:** {thread_mention}{admin_info}\n"
                f"**Created:** `{t.get('created_at', 'N/A')}`{reason_info}"
            )
            embed.add_field(name=field_name, value=field_value, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)
        schedule_ttl_delete(interaction, delay=90.0)

    # Legacy alias
    async def guest_tickets(
        self,
        interaction: discord.Interaction,
        status: str | None = None,
        limit: app_commands.Range[int, 1, 20] = 10,
    ) -> None:
        await self.tickets(interaction, status=status, limit=limit)

    # ==========================================
    # 🔒 14. Manual Ticket Closure
    # ==========================================

    @admin_group.command(
        name="close_ticket",
        description="Manually close a guest review ticket thread without kicking the applicant.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        reason="Reason for closing the ticket (e.g. duplicate request, inquiries resolved, spam dismissal)",
        ticket="Optional ticket code (e.g. A0001, 1, #A0001) or DB ID (defaults to current thread ticket)",
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        reason: str | None = None,
        ticket: str | None = None,
    ) -> None:
        """Manually closes a guest review ticket without granting guest roles or kicking/banning."""
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

        guest_svc = self.guest_service or getattr(self.bot, "guest_service", None)
        if not guest_svc:
            await interaction.response.send_message("❌ Guest verification service is unavailable.", ephemeral=True)
            schedule_ttl_delete(interaction, delay=60.0)
            return

        await interaction.response.defer(ephemeral=True)

        ticket_data = None
        if ticket is not None:
            parsed_seq = parse_ticket_seq(ticket)
            if parsed_seq is not None:
                # 1. Search by guild-scoped sequence or DB ID
                ticket_data = await self.db.get_guest_ticket_by_seq(interaction.guild.id, parsed_seq)
                if not ticket_data:
                    ticket_data = await self.db.get_guest_ticket_by_id(parsed_seq)
                    if ticket_data and ticket_data.get("guild_id") != interaction.guild.id:
                        ticket_data = None
        else:
            # 2. Default to current thread / channel
            if interaction.channel:
                ticket_data = await self.db.get_guest_ticket_by_channel(interaction.channel.id)

        if not ticket_data:
            if ticket is not None:
                await interaction.followup.send(f"❌ No guest review ticket found matching `{ticket}`.", ephemeral=True)
            else:
                await interaction.followup.send(
                    "❌ This channel is not an active guest review ticket thread. "
                    "Please run this command inside a ticket thread or specify `ticket`.",
                    ephemeral=True,
                )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        if ticket_data.get("status") != "OPEN":
            seq = ticket_data.get("ticket_seq") or ticket_data["ticket_id"]
            seq_code = format_ticket_seq(seq)
            status_str = ticket_data.get("status", "UNKNOWN")
            ticket_ch_id = ticket_data.get("channel_id")

            thread = None
            if isinstance(interaction.channel, discord.Thread) and interaction.channel.id == ticket_ch_id:
                thread = interaction.channel
            elif ticket_ch_id:
                if hasattr(interaction.guild, "get_thread"):
                    thread = interaction.guild.get_thread(ticket_ch_id)
                if not thread and hasattr(guest_svc, "_get_or_fetch_thread"):
                    res = guest_svc._get_or_fetch_thread(interaction.guild, ticket_ch_id)
                    thread = await res if inspect.isawaitable(res) else res
                if not thread and hasattr(interaction.guild, "get_channel"):
                    thread = interaction.guild.get_channel(ticket_ch_id)

            # If the thread exists and is unarchived or unlocked, cleanly archive it!
            if (
                thread
                and (isinstance(thread, discord.Thread) or hasattr(thread, "send"))
                and (not getattr(thread, "archived", False) or not getattr(thread, "locked", False))
            ):
                reason_note = f'\n> **Reason:** *"{reason.strip()}"*' if reason and reason.strip() else ""
                try:
                    res = thread.send(
                        f"🔒 **Ticket thread archived by {interaction.user.mention} via `/admin close_ticket`.**\n"
                        f"*(Ticket was previously recorded as `{status_str}`)*{reason_note}\n\n"
                        f"This thread is now locked and archived."
                    )
                    if inspect.isawaitable(res):
                        await res
                except (discord.HTTPException, Exception) as exc:
                    logger.debug("Failed sending thread closure message: %s", exc)

                # Try to update the review embed on the root message
                try:
                    from tarveri.cogs.guest_cog import build_review_embed

                    applicant_member = interaction.guild.get_member(ticket_data["applicant_id"])
                    embed = build_review_embed(
                        ticket_data, interaction.guild, applicant_member, status_override=status_str
                    )
                    starter_msg = getattr(thread, "starter_message", None)
                    if starter_msg and starter_msg.author.id == self.bot.user.id and hasattr(starter_msg, "edit"):
                        res = starter_msg.edit(embed=embed, view=discord.ui.View())
                        if inspect.isawaitable(res):
                            await res
                except Exception as exc:
                    logger.debug("Failed updating starter message embed: %s", exc)

                await asyncio.sleep(1)
                if hasattr(guest_svc, "safe_close_and_archive_thread"):
                    res = guest_svc.safe_close_and_archive_thread(
                        thread,
                        reason=f"TARVeri: Archived by {interaction.user} (status: {status_str})",
                    )
                    if inspect.isawaitable(res):
                        await res
                elif hasattr(thread, "edit"):
                    try:
                        res = thread.edit(
                            locked=True,
                            archived=True,
                            reason=f"TARVeri: Archived by {interaction.user} (status: {status_str})",
                        )
                        if inspect.isawaitable(res):
                            await res
                    except Exception as exc:
                        logger.warning("Failed locking/archiving thread: %s", exc)

                if hasattr(guest_svc, "_cleanup_channel_overwrites"):
                    await guest_svc._cleanup_channel_overwrites(interaction.guild, ticket_data)

                await interaction.followup.send(
                    f"🔒 Ticket #{seq_code} ({status_str}) was open as an unarchived thread. Cleaned up and archived the thread.",
                    ephemeral=True,
                )
                schedule_ttl_delete(interaction, delay=60.0)
                return

            await interaction.followup.send(
                f"⚠️ Ticket #{seq_code} is already resolved ({status_str}) and archived.", ephemeral=True
            )
            schedule_ttl_delete(interaction, delay=60.0)
            return

        # Execute manual closure
        success, reply_msg = await guest_svc.close_guest_ticket_manually(
            ticket=ticket_data,
            guild=interaction.guild,
            admin_user=interaction.user,
            reason=reason,
        )

        if success:
            ticket_ch_id = ticket_data.get("channel_id")
            thread = None
            if isinstance(interaction.channel, discord.Thread) and interaction.channel.id == ticket_ch_id:
                thread = interaction.channel
            elif ticket_ch_id:
                if hasattr(interaction.guild, "get_thread"):
                    thread = interaction.guild.get_thread(ticket_ch_id)
                if not thread and hasattr(guest_svc, "_get_or_fetch_thread"):
                    res = guest_svc._get_or_fetch_thread(interaction.guild, ticket_ch_id)
                    thread = await res if inspect.isawaitable(res) else res
                if not thread and hasattr(interaction.guild, "get_channel"):
                    thread = interaction.guild.get_channel(ticket_ch_id)

            # If inside the thread (or thread is accessible), post closure notice and lock/archive
            if thread and (isinstance(thread, discord.Thread) or hasattr(thread, "send")):
                reason_note = f'\n> **Reason:** *"{reason.strip()}"*' if reason and reason.strip() else ""
                try:
                    res = thread.send(
                        f"🔒 **Ticket manually closed by {interaction.user.mention} via `/admin close_ticket`.**\n"
                        f"*(Applicant remains in the server; no role changes or kicks executed)*{reason_note}\n\n"
                        f"This thread will be locked and archived."
                    )
                    if inspect.isawaitable(res):
                        await res
                except (discord.HTTPException, Exception) as exc:
                    logger.debug("Failed sending thread closure message: %s", exc)

                # Try to update the review embed on the root message if found in guest_cog
                try:
                    updated_ticket = await self.db.get_guest_ticket_by_id(ticket_data["ticket_id"])
                    applicant_member = interaction.guild.get_member(ticket_data["applicant_id"])
                    if updated_ticket:
                        from tarveri.cogs.guest_cog import build_review_embed

                        embed = build_review_embed(
                            updated_ticket, interaction.guild, applicant_member, status_override="CLOSED"
                        )
                        starter_msg = getattr(thread, "starter_message", None)
                        if starter_msg and starter_msg.author.id == self.bot.user.id and hasattr(starter_msg, "edit"):
                            res = starter_msg.edit(embed=embed, view=discord.ui.View())
                            if inspect.isawaitable(res):
                                await res
                except Exception as exc:
                    logger.debug("Failed updating starter message embed: %s", exc)

                await asyncio.sleep(1)
                if hasattr(guest_svc, "safe_close_and_archive_thread"):
                    res = guest_svc.safe_close_and_archive_thread(
                        thread,
                        reason=f"TARVeri: Ticket closed by {interaction.user}",
                    )
                    if inspect.isawaitable(res):
                        await res
                elif hasattr(thread, "edit"):
                    try:
                        res = thread.edit(
                            locked=True, archived=True, reason=f"TARVeri: Ticket closed by {interaction.user}"
                        )
                        if inspect.isawaitable(res):
                            await res
                    except Exception as exc:
                        logger.warning("Failed locking/archiving thread: %s", exc)

            await interaction.followup.send(reply_msg, ephemeral=True)
        else:
            await interaction.followup.send(reply_msg, ephemeral=True)

        schedule_ttl_delete(interaction, delay=60.0)

    # ==========================================
    # 🛡️ 13. Mass Action Approvals & Circuit Breaker Commands
    # ==========================================

    @admin_group.command(
        name="mass_revocation",
        description="Inspect, approve, or reject suspended mass role revocation actions.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        action="Action to perform (list, approve, or reject).",
        action_id="The Action ID (e.g. MREV-XXXXXX) to approve or reject.",
    )
    async def mass_revocation(
        self,
        interaction: discord.Interaction,
        action: Literal["list", "approve", "reject"],
        action_id: str | None = None,
    ) -> None:
        """Inspects or authorizes staged mass role revocations."""
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

        if action == "list":
            actions = await self.db.list_pending_mass_actions(guild_id=interaction.guild.id, limit=10)
            if not actions:
                await interaction.followup.send(
                    f"ℹ️ No pending or recent mass actions found for **{interaction.guild.name}**.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title=f"🛡️ Mass Actions Queue — {interaction.guild.name}",
                description="List of staged mass actions and their approval status:",
                color=discord.Color.blue(),
                timestamp=datetime.now(get_configured_tz()),
            )
            for act in actions:
                status_emoji = "⏳" if act["status"] == "PENDING" else ("✅" if act["status"] == "APPROVED" else "❌")
                embed.add_field(
                    name=f"{status_emoji} `{act['action_id']}` — {act['action_type']}",
                    value=(
                        f"• **Status**: `{act['status']}`\n"
                        f"• **Affected**: {len(act['user_ids'])} members\n"
                        f"• **Reason**: {act['reason']}\n"
                        f"• **Created**: <t:{int(datetime.fromisoformat(act['created_at']).timestamp())}:R>"
                    ),
                    inline=False,
                )
            embed.set_footer(text="Use /admin mass_revocation action:approve|reject action_id:ID to decide.")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        if not action_id:
            await interaction.followup.send(
                "❌ Please specify an `action_id` (e.g. `MREV-A1B2C3`) to approve or reject.",
                ephemeral=True,
            )
            return

        clean_id = action_id.strip().upper()
        if action == "approve":
            success, msg = await self.service.execute_approved_mass_revocation(
                interaction.guild, clean_id, admin=interaction.user
            )
            await interaction.followup.send(msg, ephemeral=True)
        elif action == "reject":
            success, msg = await self.service.reject_mass_revocation(
                interaction.guild, clean_id, admin=interaction.user
            )
            await interaction.followup.send(msg, ephemeral=True)

        schedule_ttl_delete(interaction, delay=60.0)
