"""
Tomiwa's Trade Efficiency Bot
Phase 2: Trade journal — RR-based logging via guided button flow.
"""

import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    ConversationHandler, CallbackQueryHandler, MessageHandler, filters
)

import db
import twelvedata_client
import scanner

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

# Minimum seconds between TwelveData API calls, to stay safely under the
# free tier's 8-calls-per-minute limit. Applied wherever we loop over
# multiple pairs/timeframes in scan jobs.
RATE_LIMIT_DELAY = 8

async def fetch_candles_safely(pair, interval, outputsize=60):
    """
    Runs the (blocking) TwelveData request in a background thread so it
    doesn't freeze the bot for other users while waiting, then pauses
    briefly afterward to respect the API's per-minute rate limit.
    """
    candles = await asyncio.to_thread(twelvedata_client.fetch_candles, pair, interval, outputsize)
    await asyncio.sleep(RATE_LIMIT_DELAY)
    return candles

# Conversation states for the /log flow
ASK_PAIR, ASK_SESSION, ASK_SETUP, ASK_PLANNED_RR, ASK_CONFIDENCE, ASK_RESULT, ASK_ACTUAL_RR = range(7)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.register_user(update.effective_user.id)
    await update.message.reply_text(
        "Bot is alive. Your data is private to your Telegram account.\n\n"
        "Commands:\n"
        "/log PAIR — start logging a trade (e.g. /log EURUSD)\n"
        "/history — see your last 10 trades\n"
        "/stats — see your all-time performance\n"
        "/weekly — see this week's performance\n"
        "/monthly — see this month's performance\n"
        "/mute — turn specific automatic messages on/off\n"
        "/watchlist — manage pairs you want scanned for setups\n"
        "/crt — check your watchlist for confirmed CRT setups right now (or /crt PAIR)\n"
        "/cancel — cancel a /log in progress\n"
        "/ping — check the bot is running\n\n"
        "You'll also get automatic weekly (Sunday) and monthly reports — "
        "use /mute anytime to turn those off if you don't want them."
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


# ---------- alert preferences (/mute) ----------

# Every automatic message type the bot can send, and its human-readable name.
# Add new entries here as future features (news, CRT scans, watchlist) are built —
# they'll automatically show up in /mute with no other changes needed.
ALERT_TYPES = [
    ("weekly_report", "Weekly Report"),
    ("monthly_report", "Monthly Report"),
    ("watchlist_scan", "Watchlist Opportunity Alerts"),
    ("crt_scan", "CRT Alerts (BOS confirmed)"),
]

# Timeframes checked for CRT, and how TwelveData labels each interval.
CRT_TIMEFRAMES = {
    "1W": "1week",
    "1D": "1day",
    "4H": "4h",
    "1H": "1h",
}


def mute_keyboard(user_id: int):
    rows = []
    for alert_type, label in ALERT_TYPES:
        enabled = db.is_alert_enabled(user_id, alert_type)
        status = "🔔 ON" if enabled else "🔕 OFF"
        rows.append([InlineKeyboardButton(f"{label}: {status}", callback_data=f"mute:{alert_type}")])
    return InlineKeyboardMarkup(rows)


async def mute_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Tap to toggle any automatic message on/off:",
        reply_markup=mute_keyboard(update.effective_user.id)
    )


async def toggle_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    alert_type = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    currently_on = db.is_alert_enabled(user_id, alert_type)
    db.set_alert_enabled(user_id, alert_type, not currently_on)
    await query.edit_message_text(
        "Tap to toggle any automatic message on/off:",
        reply_markup=mute_keyboard(user_id)
    )


# ---------- scheduled jobs (automatic weekly/monthly reports) ----------

async def send_weekly_reports(context: ContextTypes.DEFAULT_TYPE):
    """Runs every Sunday. Sends each opted-in user their week's performance."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    for user_id in db.get_all_user_ids():
        if not db.is_alert_enabled(user_id, "weekly_report"):
            continue
        summary = db.get_stats(user_id, since=since)
        if not summary:
            continue  # don't message users with nothing to report
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=format_stats(summary, "📊 Your weekly performance")
            )
        except Exception as e:
            logger.warning(f"Failed to send weekly report to {user_id}: {e}")


async def send_monthly_reports(context: ContextTypes.DEFAULT_TYPE):
    """Runs daily, but only actually sends on the 1st of each month (previous month's data)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    if now.day != 1:
        return  # only fire on the 1st

    since = (now - timedelta(days=30)).isoformat()

    for user_id in db.get_all_user_ids():
        if not db.is_alert_enabled(user_id, "monthly_report"):
            continue
        summary = db.get_stats(user_id, since=since)
        if not summary:
            continue
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=format_stats(summary, "📅 Your monthly performance")
            )
        except Exception as e:
            logger.warning(f"Failed to send monthly report to {user_id}: {e}")


# ---------- watchlist commands ----------

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /watchlist — show your current list
    /watchlist add PAIR [PAIR2 PAIR3 ...] — add one or more pairs
    /watchlist remove PAIR — remove a pair
    """
    args = context.args
    user_id = update.effective_user.id

    if not args:
        pairs = db.get_watchlist(user_id)
        if not pairs:
            await update.message.reply_text(
                "Your watchlist is empty.\nAdd pairs: /watchlist add EUR/USD GBP/USD NDX"
            )
            return
        await update.message.reply_text(
            "Your watchlist:\n" + "\n".join(pairs) +
            "\n\nRemove one: /watchlist remove PAIR"
        )
        return

    action = args[0].lower()
    if action == "add" and len(args) >= 2:
        added = []
        for raw_pair in args[1:]:
            pair = raw_pair.upper()
            db.add_to_watchlist(user_id, pair)
            added.append(pair)
        await update.message.reply_text(
            f"Added to your watchlist: {', '.join(added)}\n"
            f"Watchlist scan every 4h, CRT scan on 1W/1D/4H/1H."
        )
    elif action == "remove" and len(args) == 2:
        pair = args[1].upper()
        db.remove_from_watchlist(user_id, pair)
        await update.message.reply_text(f"Removed {pair} from your watchlist.")
    else:
        await update.message.reply_text(
            "Usage:\n/watchlist — show your list\n"
            "/watchlist add PAIR [PAIR2 PAIR3 ...] — e.g. /watchlist add EUR/USD GBP/USD NDX\n"
            "/watchlist remove PAIR"
        )


# ---------- watchlist scan job ----------

async def run_watchlist_scan(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs at each 4H candle close. Fetches each unique watched pair ONCE (not
    per user, to save API calls), scans it for setups, and notifies every
    user watching that pair who hasn't already been alerted for this exact candle.
    """
    pairs = db.get_all_watchlist_pairs()

    for pair in pairs:
        candles = await fetch_candles_safely(pair, interval="4h", outputsize=60)
        if not candles:
            logger.warning(f"Watchlist scan: no data for {pair}")
            continue

        signals = scanner.scan(candles)
        if not signals:
            continue

        last_candle_time = candles[-1]["datetime"]
        watchers = db.get_users_watching(pair)

        for user_id in watchers:
            if not db.is_alert_enabled(user_id, "watchlist_scan"):
                continue

            new_signals = [
                (sig_type, msg) for sig_type, msg in signals
                if not db.already_alerted(user_id, pair, sig_type, last_candle_time)
            ]
            if not new_signals:
                continue

            lines = [f"👀 Hey, you should check {pair} (4H) —"]
            for sig_type, msg in new_signals:
                lines.append(f"• {msg}")
                db.mark_alerted(user_id, pair, sig_type, last_candle_time)

            try:
                await context.bot.send_message(chat_id=user_id, text="\n".join(lines))
            except Exception as e:
                logger.warning(f"Failed to send watchlist alert to {user_id}: {e}")


# ---------- CRT: manual command ----------

async def crt_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /crt — check your whole watchlist for confirmed CRT setups right now
    /crt PAIR — check just one pair
    Only replies if a confirmed setup is actually found — stays silent otherwise.
    Runs regardless of your /mute setting, since this is an on-demand check,
    not an automatic push.
    """
    user_id = update.effective_user.id
    args = context.args

    pairs = [args[0].upper()] if args else db.get_watchlist(user_id)
    if not pairs:
        await update.message.reply_text(
            "Nothing to check. Add a pair to your watchlist first (/watchlist add EURUSD) "
            "or specify one directly: /crt EURUSD"
        )
        return

    lines = []
    for pair in pairs:
        for tf_label, tf_interval in CRT_TIMEFRAMES.items():
            candles = await fetch_candles_safely(pair, interval=tf_interval, outputsize=60)
            if not candles:
                continue
            signal = scanner.detect_crt(candles)
            if signal:
                lines.append(f"{pair} ({tf_label}) — {signal}")

    if lines:
        await update.message.reply_text("\n".join(lines))
    # else: stay silent, no confirmed setup found


# ---------- CRT: scheduled scan ----------

async def run_crt_scan(context: ContextTypes.DEFAULT_TYPE):
    """
    Scheduled CRT scan. Which timeframes to check are passed in via
    context.job.data — daily runs check 1W/1D, 4-hourly runs check 4H/1H.
    Respects each user's crt_scan mute setting.
    """
    timeframes_to_check = context.job.data
    pairs = db.get_all_watchlist_pairs()

    for pair in pairs:
        for tf_label in timeframes_to_check:
            tf_interval = CRT_TIMEFRAMES[tf_label]
            candles = await fetch_candles_safely(pair, interval=tf_interval, outputsize=60)
            if not candles:
                logger.warning(f"CRT scan: no data for {pair} {tf_label}")
                continue

            signal = scanner.detect_crt(candles)
            if not signal:
                continue

            last_candle_time = candles[-1]["datetime"]
            signal_key = f"crt_{tf_label}"
            watchers = db.get_users_watching(pair)

            for user_id in watchers:
                if not db.is_alert_enabled(user_id, "crt_scan"):
                    continue
                if db.already_alerted(user_id, pair, signal_key, last_candle_time):
                    continue

                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"👀 CRT confirmed on {pair} ({tf_label}) —\n{signal}"
                    )
                    db.mark_alerted(user_id, pair, signal_key, last_candle_time)
                except Exception as e:
                    logger.warning(f"Failed to send CRT alert to {user_id}: {e}")


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
    app.add_handler(CommandHandler("mute", mute_menu))
    app.add_handler(CallbackQueryHandler(toggle_alert, pattern="^mute:"))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("crt", crt_check))

    # Schedule automatic reports.
    # Times are in UTC — adjust the `time=` values below if you want them
    # to land at a specific local hour for you.
    from datetime import time
    app.job_queue.run_daily(send_weekly_reports, time=time(hour=20, minute=0), days=(6,))  # Sunday
    app.job_queue.run_daily(send_monthly_reports, time=time(hour=20, minute=5))  # checks for the 1st internally
    # Scan at fixed 4H candle-close times, starting from forex market open.
    # 23:00 in Nigeria (WAT, UTC+1) = 22:00 UTC — the schedule below starts
    # there and repeats every 4 hours: 22:00, 02:00, 06:00, 10:00, 14:00, 18:00 UTC.
    for hour in (22, 2, 6, 10, 14, 18):
        app.job_queue.run_daily(run_watchlist_scan, time=time(hour=hour, minute=1))
        # CRT on the fast timeframes runs on the same 4-hourly schedule.
        app.job_queue.run_daily(run_crt_scan, time=time(hour=hour, minute=3), data=["4H", "1H"])
    # CRT on 1W/1D only needs checking once a day — no point checking a
    # weekly candle every 4 hours, it hasn't changed.
    # 10:50pm in Nigeria (WAT, UTC+1) = 21:50 UTC.
    app.job_queue.run_daily(run_crt_scan, time=time(hour=21, minute=50), data=["1W", "1D"])

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
