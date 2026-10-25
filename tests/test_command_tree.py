"""Snapshot of the slash-command tree. Refactors must leave it unchanged.

Regenerate deliberately with TARVERI_UPDATE_SNAPSHOT=1 when a command is added or changed on purpose.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import discord
from discord import app_commands
from discord.ext import commands

from tarveri.cogs.admin_cog import AdminCog
from tarveri.cogs.card_cog import CardCog
from tarveri.cogs.guest_cog import GuestCog
from tarveri.cogs.random_tag_cog import RandomTagCog
from tarveri.cogs.verification_cog import VerificationCog

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "command_tree.json"


def _describe(command) -> dict:
    entry = {
        "name": command.name,
        "description": getattr(command, "description", None),
        "default_permissions": str(command.default_permissions.value) if command.default_permissions else None,
    }
    if isinstance(command, app_commands.Group):
        entry["kind"] = "group"
        entry["children"] = sorted((_describe(child) for child in command.commands), key=lambda item: item["name"])
    elif isinstance(command, app_commands.ContextMenu):
        entry["kind"] = "context_menu"
        entry["type"] = command.type.name
    else:
        entry["kind"] = "command"
        entry["parameters"] = [
            {"name": p.name, "required": p.required, "type": p.type.name} for p in command.parameters
        ]
    return entry


async def _build_command_tree() -> list[dict]:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    db = MagicMock()
    service = MagicMock()
    rate_limiter = MagicMock()
    await bot.add_cog(VerificationCog(bot=bot, db=db, service=service, rate_limiter=rate_limiter))
    await bot.add_cog(AdminCog(bot, db, service, rate_limiter, admin_role_name="TARVeri Admin"))
    await bot.add_cog(GuestCog(bot=bot, db=db, guest_service=MagicMock(), verification_service=service))
    await bot.add_cog(CardCog(bot=bot, db=db, card_service=MagicMock(), verification_service=service))
    await bot.add_cog(RandomTagCog(bot=bot, service=MagicMock()))

    commands_tree = [_describe(c) for c in bot.tree.get_commands()]
    await bot.close()
    return sorted(commands_tree, key=lambda item: item["name"])


async def test_command_tree_matches_snapshot():
    tree = await _build_command_tree()
    rendered = json.dumps(tree, indent=2, sort_keys=True) + "\n"

    if os.environ.get("TARVERI_UPDATE_SNAPSHOT"):
        SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
        SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")

    assert SNAPSHOT_PATH.exists(), "Snapshot missing: run with TARVERI_UPDATE_SNAPSHOT=1"
    assert rendered == SNAPSHOT_PATH.read_text(encoding="utf-8")
