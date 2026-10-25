#!/usr/bin/env bash
# ==============================================================================
# TARVeri updater: bot settings only. The update logic is bot_update_lib.sh, vendored from
# tarbot-console (the updater-drift CI job fails if the copy differs from the pinned commit).
# ==============================================================================

BOT_NAME="TARVeri"
BOT_ENV_PREFIX="TARVERI"
BOT_REPO_SLUG="TARBot-OSS/TARVeri-bot"
BOT_LEGACY_REMOTE_RE="Dellrall/(Student-verifier|TARVeri)"
BOT_DEFAULT_DB="tarveri.db"
BOT_DEFAULT_SERVICE="tarveri"
BOT_START_ARGS="tarveri_bot.py"
BOT_COMPILE_TARGETS="tarveri tarveri_bot.py"
BOT_BACKUP_PREFIX="tarveri"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bot_update_lib.sh
source "${SCRIPT_DIR}/bot_update_lib.sh"
bot_update_main "$@"
