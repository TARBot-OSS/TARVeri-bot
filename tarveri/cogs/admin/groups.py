"""Command groups shared by the admin cog and its area mixins."""

import discord
from discord import app_commands

admin_group = app_commands.Group(
    name="admin",
    description="TARVeri Administrator Control Center and Server Operations",
    default_permissions=discord.Permissions(administrator=True),
)

society_bridge_group = app_commands.Group(
    name="society_bridge",
    description="TARClub society cross-bot integration commands",
    default_permissions=discord.Permissions(administrator=True),
)

# ==========================================
# 🚫 5b. Per-Server Blacklist Management
# ==========================================

blacklist_group = app_commands.Group(
    name="blacklist",
    description="Per-server blacklist management for Discord users, Student IDs, and emails.",
    parent=admin_group,
)
