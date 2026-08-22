"""
Tomiwa's Trade Efficiency Bot
Phase 2: Trade journal — RR-based logging via guided button flow.
"""

import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    ConversationHandler, CallbackQueryHandler, MessageHandler, filters
)

import db

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN not found. Set it as an environment variable "
        "(Railway dashboard, or a local .env file)."
    )

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states for the /log flow
ASK_PAIR, ASK_SESSION, ASK_SETUP, ASK_PLANNED_RR, ASK_CONFIDENCE, ASK_RESULT, ASK_ACTUAL_RR = range(7)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot is alive. Your data is private to your Telegram account.\n\n"
        "Commands:\n"
        "/log PAIR — start logging a trade (e.g. /log EURUSD)\n"
        "/history — see your last 10 trades\n"
        "/stats — see your all-time performance\n"
        "/weekly — see this week's performance\n"
        "/monthly — see this month's performance\n"
        "/cancel — cancel a /log in progress\n"
        "/ping — check the bot is running"
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong. Still running.")


# ---------- /log conversation flow ----------

def buttons(options):
    """Helper: turns a list of strings into a single row of inline buttons."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(o, callback_data=o) for o in options]])


async def log_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /log. If pair is given, skip straight to session buttons."""
    args = context.args
    if args:
        context.user_data["pair"] = args[0].upper()
        await update.message.reply_text(
            f"Pair: {context.user_data['pair']}\nSession?",
            reply_markup=buttons(["Asian", "London", "NY", "Overlap"])
        )
        return ASK_SESSION
    else:
        await update.message.reply_text("What pair? (e.g. EURUSD)")
        return ASK_PAIR


async def receive_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pair"] = update.message.text.upper().strip()
    await update.message.reply_text(
        f"Pair: {context.user_data['pair']}\nSession?",
        reply_markup=buttons(["Asian", "London", "NY", "Overlap"])
    )
    return ASK_SESSION


async def receive_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["session"] = query.data
    await query.edit_message_text(f"Session: {query.data}")
    await query.message.reply_text(
        "Setup?",
        reply_markup=buttons(["Breakout", "Pullback", "Reversal", "Other"])
    )
    return ASK_SETUP


async def receive_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["setup"] = query.data
    await query.edit_message_text(f"Setup: {query.data}")
    await query.message.reply_text("Planned RR? (e.g. 3 for 1:3)")
    return ASK_PLANNED_RR


async def receive_planned_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["planned_rr"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a number, e.g. 3")
        return ASK_PLANNED_RR

    await update.message.reply_text(
        "Confidence at entry? (1 = low, 5 = high)",
        reply_markup=buttons(["1", "2", "3", "4", "5"])
    )
    return ASK_CONFIDENCE


async def receive_confidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["confidence"] = int(query.data)
    await query.edit_message_text(f"Confidence: {query.data}/5")
    await query.message.reply_text(
        "Result?",
        reply_markup=buttons(["Win", "Loss", "Breakeven"])
    )
    return ASK_RESULT


async def receive_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["result"] = query.data.lower()
    await query.edit_message_text(f"Result: {query.data}")
    await query.message.reply_text("Actual RR achieved? (e.g. 2.5, or -1 for a loss)")
    return ASK_ACTUAL_RR


async def receive_actual_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        actual_rr = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a number, e.g. 2.5 or -1")
        return ASK_ACTUAL_RR

    user_data = context.user_data
    user_id = update.effective_user.id

    db.log_trade(
        user_id=user_id,
        pair=user_data["pair"],
        session=user_data["session"],
        setup=user_data["setup"],
        planned_rr=user_data["planned_rr"],
        confidence=user_data["confidence"],
        result=user_data["result"],
        actual_rr=actual_rr,
    )

    await update.message.reply_text(
        f"Logged ✅\n"
        f"{user_data['pair']} | {user_data['session']} | {user_data['setup']}\n"
        f"Planned RR: {user_data['planned_rr']} | Actual RR: {actual_rr:+.2f}\n"
        f"Confidence: {user_data['confidence']}/5 | Result: {user_data['result']}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Log cancelled.")
    return ConversationHandler.END


# ---------- history / stats / reports ----------

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = db.get_history(user_id, limit=10)

    if not rows:
        await update.message.reply_text("No trades logged yet. Use /log to add one.")
        return

    lines = [f"Your last {len(rows)} trades:\n"]
    for pair, session, setup, planned_rr, confidence, result, actual_rr, logged_at in rows:
        date = logged_at.split("T")[0]
        lines.append(
            f"{date} — {pair} | {session} | {setup} | RR {planned_rr}→{actual_rr:+.2f} | "
            f"conf {confidence}/5 | {result}"
        )

    await update.message.reply_text("\n".join(lines))


def format_stats(summary: dict, title: str) -> str:
    return (
        f"{title}\n\n"
        f"Total trades: {summary['total_trades']}\n"
        f"Wins: {summary['wins']} | Losses: {summary['losses']} | Breakeven: {summary['breakeven']}\n"
        f"Win rate: {summary['win_rate']}%\n"
        f"Total RR: {summary['total_rr']:+.2f}\n"
        f"Avg RR per trade: {summary['avg_rr']:+.2f}\n"
        f"Avg confidence: {summary['avg_confidence']}/5"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    summary = db.get_stats(user_id)
    if not summary:
        await update.message.reply_text("No trades logged yet. Use /log to add one.")
        return
    await update.message.reply_text(format_stats(summary, "All-time performance"))


async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timedelta, timezone
    user_id = update.effective_user.id
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    summary = db.get_stats(user_id, since=since)
    if not summary:
        await update.message.reply_text("No trades logged in the past 7 days.")
        return
    await update.message.reply_text(format_stats(summary, "This week's performance"))


async def monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timedelta, timezone
    user_id = update.effective_user.id
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    summary = db.get_stats(user_id, since=since)
    if not summary:
        await update.message.reply_text("No trades logged in the past 30 days.")
        return
    await update.message.reply_text(format_stats(summary, "This month's performance"))


def main():
    db.init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    log_conversation = ConversationHandler(
        entry_points=[CommandHandler("log", log_start)],
        states={
            ASK_PAIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pair)],
            ASK_SESSION: [CallbackQueryHandler(receive_session)],
            ASK_SETUP: [CallbackQueryHandler(receive_setup)],
            ASK_PLANNED_RR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_planned_rr)],
            ASK_CONFIDENCE: [CallbackQueryHandler(receive_confidence)],
            ASK_RESULT: [CallbackQueryHandler(receive_result)],
            ASK_ACTUAL_RR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_actual_rr)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(log_conversation)
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("weekly", weekly))
    app.add_handler(CommandHandler("monthly", monthly))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
