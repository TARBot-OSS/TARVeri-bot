"""
Admin Commands, Interactive Dashboard & Audit Tools for TARVeri.
"""

from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from tarveri.cogs.admin import groups
from tarveri.cogs.admin.blacklist_mixin import AdminBlacklistCommands
from tarveri.cogs.admin.settings_mixin import AdminSettingsCommands
from tarveri.cogs.admin.society_bridge_mixin import AdminSocietyBridgeCommands
from tarveri.cogs.admin.status_mixin import AdminStatusCommands
from tarveri.cogs.admin.users_mixin import AdminUserCommands
from tarveri.database import Database
from tarveri.rate_limiter import RateLimiter
from tarveri.services.guest_service import GuestService
from tarveri.services.log_service import LogRotationService
from tarveri.services.update_checker import UpdateCheckerService
from tarveri.services.uptime_service import UptimeService
from tarveri.services.verification_service import VerificationService
from tarveri.views.admin_views import MassRevocationApprovalView

logger = logging.getLogger("tarveri")


def is_admin_or_has_role(interaction: discord.Interaction, admin_role_name: str) -> bool:
    """Checks if invoking user has Administrator permission, the configured Admin role, or a standard admin/staff role."""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    from tarveri.cogs.guest_cog import get_admin_role_or_fallback

    admin_role = get_admin_role_or_fallback(interaction.guild, admin_role_name)
    if admin_role and admin_role in interaction.user.roles:
        return True
    return any(
        getattr(r, "name", "").lower() == admin_role_name.lower() for r in getattr(interaction.user, "roles", [])
    )


class AdminCog(
    AdminStatusCommands,
    AdminUserCommands,
    AdminSettingsCommands,
    AdminBlacklistCommands,
    AdminSocietyBridgeCommands,
    commands.Cog,
    name="Admin",
):
    """Consolidated Administrator Control Center and Server Operations."""

    admin_group = groups.admin_group
    society_bridge_group = groups.society_bridge_group
    blacklist_group = groups.blacklist_group

    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        service: VerificationService,
        rate_limiter: RateLimiter,
        admin_role_name: str,
        update_checker: UpdateCheckerService | None = None,
        log_rotator: LogRotationService | None = None,
        guest_service: GuestService | None = None,
        uptime_service: UptimeService | None = None,
        dead_letter_service: Any = None,
    ):
        self.bot = bot
        self.db = db
        self.service = service
        self.rate_limiter = rate_limiter
        self.admin_role_name = admin_role_name
        self.update_checker = update_checker
        self.log_rotator = log_rotator
        self.guest_service = guest_service
        self.uptime_service = uptime_service
        self.dead_letter_service = dead_letter_service

    def _check_admin(self, interaction: discord.Interaction) -> bool:
        return is_admin_or_has_role(interaction, self.admin_role_name)


__all__ = ["AdminCog", "MassRevocationApprovalView", "is_admin_or_has_role"]


async def setup(bot: commands.Bot) -> None:
    pass
