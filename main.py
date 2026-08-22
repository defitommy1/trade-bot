"""
Tomiwa's Trade Efficiency Bot
Phase 1: Skeleton — just proves the bot is alive and responding.
"""

import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# On Railway, this is set as an environment variable in the dashboard.
# Locally, you can set it in a .env file (see local_run.py) for testing.
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN not found. Set it as an environment variable "
        "(Railway dashboard, or a local .env file)."
    )

# Basic logging so you can see what the bot is doing in the terminal
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds when you send /start"""
    await update.message.reply_text(
        "Bot is alive, Tomiwa. Connection confirmed."
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple health check command"""
    await update.message.reply_text("Pong. Still running.")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
