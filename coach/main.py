"""Coach entrypoint.

Usage (from the repo root):
    python -m coach.main            # run on schedule (long-running)
    python -m coach.main --now      # send the morning briefing once, right away
    python -m coach.main --chat-id  # show the chat ID to put in .env (message your bot first)
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv
from telegram import Bot, BotCommand, BotCommandScopeChat, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from coach.briefing import Briefing, build_briefing, build_evening, build_midday, build_phrase_help
from coach.delivery.telegram import (
    EVENING_DONE,
    EVENING_DROP,
    EVENING_MOVE,
    KEYBOARD,
    TASK_TAP,
    WAKE_BUTTON,
    evening_buttons,
    recent_chats,
    send_briefing,
    task_buttons,
)
from coach.sources.content import (
    REVIEW_AFTER_DAYS,
    content_kind,
    load_history,
    pick_content,
    pick_quote,
    recent_phrase,
    record_sent,
    sent_keys,
)
from coach.sources.tasks import TasksFileError, add_task, drop_task, load_tasks, move_to_tomorrow, toggle_done
from coach.sources.weather import fetch_weather
from coach.voice.tts import EdgeTTS, render

log = logging.getLogger("coach")

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
DATA_DIR = PACKAGE_DIR / "data"
MORNING_AUDIO_PATH = DATA_DIR / "audio" / "morning.mp3"
EVENING_AUDIO_PATH = DATA_DIR / "audio" / "evening.mp3"
PHRASE_AUDIO_PATH = DATA_DIR / "audio" / "phrase.mp3"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "coach.log"
TASKS_PATH = DATA_DIR / "tasks.json"
DAY_LOG_PATH = DATA_DIR / "log.json"  # what got done and what was sent, each day

GRACE = timedelta(hours=3)  # laptop asleep at check-in time? Still send if it wakes within 3 hours
WAKE = "wake"  # morning setting in config.yaml: send when Ty says he's up
CHECK_EVERY_SECONDS = 60
SEND_ATTEMPTS = 3
RETRY_SECONDS = 20

HELP = (
    "Here's what I can do:\n"
    "/tasks: today's list. Tap a task to check it off, tap again to undo.\n"
    "/add Finish resume: add a task. It stays on your list until it's done.\n"
    "/add tomorrow Call mom: add a task for tomorrow only.\n"
    "/phrase: this week's phrase again, word by word and slowly, with the spelling.\n"
    f'On weekends, tap "{WAKE_BUTTON}" when you\'re awake and I\'ll send your briefing.\n'
    "Midday on weekdays I check what's left, and in the evening I recap the day. "
    "Tap anything you finished, or move it to tomorrow."
)
CANT_READ_YET = "I can't read regular messages yet. For now: /tasks for today's list, /add to add a task, /help for the rest."


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def prepare_morning(config: dict, now: datetime) -> tuple[Briefing, Path | None, dict[str, str]]:
    """Gather today's info, build the briefing, and save it as an MP3 (None if the voice fails).
    Also returns what to record in the history once it's sent."""
    today = now.date()
    location = config["location"]
    weather = await asyncio.to_thread(
        fetch_weather, location["lat"], location["lon"], config["timezone"], config["temperature_unit"]
    )
    try:
        tasks = [task for task in load_tasks(TASKS_PATH, today) if not task.done]  # already checked off: skip
    except TasksFileError as e:
        log.warning("%s", e)
        tasks = None
    history = load_history(DAY_LOG_PATH)
    item = await asyncio.to_thread(
        pick_content, today, config["content_rotation"], config["language_to_learn"], history=history
    )
    quote = pick_quote(history)
    briefing = build_briefing(config["owner_name"], location["name"], now, weather, tasks, item, quote)
    return briefing, await _record(briefing, config, MORNING_AUDIO_PATH), sent_keys(item, quote)


async def _record(script: Briefing, config: dict, path: Path) -> Path | None:
    """Save the script as an MP3 at path, or return None if the voice fails (text only, then)."""
    try:
        audio = await render(script.segments, EdgeTTS(), config["voice"], config["phrase_voice"])
    except Exception as e:  # edge-tts fails in several ways; any of them means text only
        log.warning("Voice unavailable, sending text only: %s", e)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return path


async def _send_with_retries(send: Callable[[], Awaitable], what: str) -> None:
    """Run a Telegram send, retrying if the network is briefly down."""
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            await send()
            log.info("%s sent", what)
            return
        except NetworkError as e:
            if attempt == SEND_ATTEMPTS:
                raise
            log.warning("Telegram send failed (%s); retrying in %s seconds", e, RETRY_SECONDS)
            await asyncio.sleep(RETRY_SECONDS)


async def run_morning(config: dict, bot: Bot, chat_id: str, now: datetime) -> None:
    """Build today's briefing and send it, with today's task buttons."""
    briefing, audio_path, sent = await prepare_morning(config, now)
    buttons = today_buttons(now.date())
    await _send_with_retries(lambda: send_briefing(bot, chat_id, briefing.text, audio_path, buttons),
                             "Morning briefing")
    record_sent(DAY_LOG_PATH, now.date(), sent)  # only once it's out, so a failed send gets the same picks


async def run_midday(config: dict, bot: Bot, chat_id: str, now: datetime) -> None:
    """One line on what's left, with today's task buttons. Skipped when there are no tasks."""
    today = now.date()
    try:
        tasks = load_tasks(TASKS_PATH, today)
    except TasksFileError as e:
        log.warning("Midday check-in skipped: %s", e)
        return
    text = build_midday(tasks)
    if text is None:
        log.info("Midday check-in skipped: no tasks today")
        return
    buttons = task_buttons(tasks, today) if any(not task.done for task in tasks) else KEYBOARD
    await _send_with_retries(lambda: bot.send_message(chat_id, text, reply_markup=buttons), "Midday check-in")


async def run_evening(config: dict, bot: Bot, chat_id: str, now: datetime) -> None:
    """How today went and a look at tomorrow: a short voice note, with buttons for what's still open."""
    today = now.date()
    try:
        tasks, upcoming = load_tasks(TASKS_PATH, today), load_tasks(TASKS_PATH, today + timedelta(days=1))
    except TasksFileError as e:
        log.warning("%s", e)
        tasks = upcoming = None
    location = config["location"]
    weather = await asyncio.to_thread(
        fetch_weather, location["lat"], location["lon"], config["timezone"], config["temperature_unit"], days_ahead=1
    )
    review = recent_phrase(today, load_history(DAY_LOG_PATH), config["language_to_learn"], ages=REVIEW_AFTER_DAYS)
    evening = build_evening(config["owner_name"], tasks, weather, upcoming, review)
    audio_path = await _record(evening, config, EVENING_AUDIO_PATH)
    buttons = evening_buttons(tasks or [], today)
    await _send_with_retries(lambda: send_briefing(bot, chat_id, evening.text, audio_path, buttons),
                             "Evening check-in")


def _morning_setting(schedule: dict, day: date) -> str:
    """config.yaml has one morning setting for weekdays and one for weekends: a time, or WAKE."""
    return schedule["morning_weekends" if day.weekday() >= 5 else "morning_weekdays"]


def morning_time(schedule: dict, day: date) -> time:
    """When the briefing goes out without a tap: the set time, or on wake days the fallback."""
    setting = _morning_setting(schedule, day)
    return time.fromisoformat(schedule["wake_latest"] if setting == WAKE else setting)


def wake_reply(sent_at: datetime, schedule: dict, last_sent: date | None, text: str | None) -> str | None:
    """Ty messaged the bot at sent_at. None means send today's briefing now; otherwise, a short reply."""
    if last_sent == sent_at.date():
        return "Today's briefing already went out. It's just above." if text == WAKE_BUTTON else CANT_READ_YET
    setting = _morning_setting(schedule, sent_at.date())
    if setting == WAKE:
        earliest = time.fromisoformat(schedule["wake_earliest"])
        if sent_at.time() < earliest:
            return f"Too early for the briefing. Tap again after {_clock(earliest)}."
        return None
    start = time.fromisoformat(setting)
    if sent_at.time() < start:
        return f"Your briefing comes at {_clock(start)} today."
    return None  # past the set time and nothing sent yet (the laptop was probably asleep)


def _clock(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def parse_add(args: str, today: date) -> tuple[str, date | None]:
    """'/add tomorrow Call mom' is for tomorrow only; anything else stays on the list until it's done."""
    first, _, rest = args.strip().partition(" ")
    if first.lower() == "tomorrow":
        return rest.strip(), today + timedelta(days=1)
    return args.strip(), None


def today_buttons(day: date, evening: bool = False) -> InlineKeyboardMarkup | None:
    """The day's task buttons (the evening version, if asked), or None if there are no tasks
    or tasks.json can't be read."""
    try:
        tasks = load_tasks(TASKS_PATH, day)
    except TasksFileError as e:
        log.warning("%s", e)
        return None
    return evening_buttons(tasks, day) if evening else task_buttons(tasks, day)


def slot_due(now: datetime, start: time, last_sent: date | None, grace: timedelta = GRACE) -> bool:
    """True if today's check-in hasn't gone out and it's between its time and the grace cutoff."""
    begins = now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    return last_sent != now.date() and begins <= now < begins + grace


def load_last_sent(path: Path = STATE_PATH, slot: str = "morning") -> date | None:
    """The last day this slot (morning, midday or evening) went out."""
    try:
        return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))[f"last_{slot}"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_last_sent(day: date | None, path: Path = STATE_PATH, slot: str = "morning") -> None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state[f"last_{slot}"] = day.isoformat() if day else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


async def send_once(slot: str, send: Callable[[], Awaitable], now: datetime) -> bool:
    """Run today's check-in for this slot. Today is claimed first, so the clock check and a tap can't
    both send it; if sending fails, the claim is undone so the next check or tap tries again."""
    last_sent = load_last_sent(slot=slot)
    save_last_sent(now.date(), slot=slot)
    try:
        await send()
        return True
    except Exception:
        log.exception("The %s check-in failed", slot)
        save_last_sent(last_sent, slot=slot)
        return False


async def send_morning_once(config: dict, bot: Bot, chat_id: str, now: datetime) -> bool:
    return await send_once("morning", lambda: run_morning(config, bot, chat_id, now), now)


async def check_schedule(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute. Watching the clock, instead of setting timers, means a check-in still
    goes out if the laptop was asleep or the coach restarted at its time (up to 3 hours late)."""
    config, chat_id, bot = context.bot_data["config"], context.bot_data["chat_id"], context.bot
    schedule = config["schedule"]
    now = datetime.now(ZoneInfo(config["timezone"]))
    today = now.date()
    if slot_due(now, morning_time(schedule, today), load_last_sent()):
        await send_morning_once(config, bot, chat_id, now)
    if today.weekday() < 5 and slot_due(now, time.fromisoformat(schedule["midday"]), load_last_sent(slot="midday")):
        await send_once("midday", lambda: run_midday(config, bot, chat_id, now), now)
    if slot_due(now, time.fromisoformat(schedule["evening"]), load_last_sent(slot="evening")):
        await send_once("evening", lambda: run_evening(config, bot, chat_id, now), now)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A message from Ty. On wake days, the first one after wake_earliest sends the briefing."""
    config, chat_id = context.bot_data["config"], context.bot_data["chat_id"]
    tz = ZoneInfo(config["timezone"])
    message = update.effective_message
    sent_at = message.date.astimezone(tz)
    if sent_at.date() != datetime.now(tz).date():
        return  # sent before midnight and only picked up now because the laptop was asleep
    reply = wake_reply(sent_at, config["schedule"], load_last_sent(), message.text)
    if reply:
        await message.reply_text(reply, reply_markup=KEYBOARD)
        return
    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
    if not await send_morning_once(config, context.bot, chat_id, datetime.now(tz)):
        await message.reply_text("Something went wrong building your briefing. Tap again in a minute.",
                                 reply_markup=KEYBOARD)


def _today(context: ContextTypes.DEFAULT_TYPE) -> date:
    return datetime.now(ZoneInfo(context.bot_data["config"]["timezone"])).date()


async def on_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tasks: today's list as buttons."""
    today = _today(context)
    try:
        buttons = task_buttons(load_tasks(TASKS_PATH, today), today)
    except TasksFileError as e:
        await update.effective_message.reply_text(f"{e}. Check it for a typo.", reply_markup=KEYBOARD)
        return
    if buttons is None:
        await update.effective_message.reply_text("Nothing on your list today. Add one with /add.",
                                                  reply_markup=KEYBOARD)
    else:
        await update.effective_message.reply_text("Today's list. Tap a task when it's done:", reply_markup=buttons)


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add <task>, or /add tomorrow <task>."""
    today = _today(context)
    text, day = parse_add(update.effective_message.text.partition(" ")[2], today)
    if not text:
        reply = "Add what? For example: /add Finish resume, or /add tomorrow Call mom."
    else:
        try:
            if add_task(TASKS_PATH, text, today, day):
                reply = f"Added for tomorrow: {text}" if day else f"Added: {text}"
            else:
                reply = f"That's already on your list: {text}"
        except TasksFileError as e:
            reply = f"{e}, so I didn't add it. Check it for a typo."
    await update.effective_message.reply_text(reply, reply_markup=KEYBOARD)


async def on_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/phrase: the latest phrase again, word by word and slowly, with the spelling written out."""
    config, chat_id = context.bot_data["config"], context.bot_data["chat_id"]
    today = _today(context)
    phrase = recent_phrase(today, load_history(DAY_LOG_PATH), config["language_to_learn"])
    if phrase is None:
        upcoming = (today + timedelta(days=n) for n in range(1, 8))
        next_day = next((day for day in upcoming if content_kind(day, config["content_rotation"]) == "phrase"), None)
        when = f"with {next_day:%A}'s briefing" if next_day else "once phrases are on in config.yaml"
        await update.effective_message.reply_text(f"No phrase yet. Your first one comes {when}.",
                                                  reply_markup=KEYBOARD)
        return
    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
    help_script = build_phrase_help(phrase)
    audio_path = await _record(help_script, config, PHRASE_AUDIO_PATH)
    await send_briefing(context.bot, chat_id, help_script.text, audio_path)


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP, reply_markup=KEYBOARD)


async def on_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("I don't know that one. Try /help.", reply_markup=KEYBOARD)


async def on_task_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A tap on a task button: check it off (or back on), move it to tomorrow, or drop it,
    then redraw that message's buttons."""
    query = update.callback_query
    if update.effective_chat.id != int(context.bot_data["chat_id"]):
        return
    today = _today(context)
    action, day, key = query.data.split(":")
    if day != today.isoformat():
        await query.answer("That list is from an earlier day. Send /tasks for today's.")
        return
    try:
        if action == EVENING_MOVE:
            task = move_to_tomorrow(TASKS_PATH, key, today)
            toast = task and f"Moved to tomorrow: {task.text}"
        elif action == EVENING_DROP:
            task = drop_task(TASKS_PATH, key, today)
            toast = task and f"Dropped: {task.text}"
        else:
            task = toggle_done(TASKS_PATH, DAY_LOG_PATH, key, today)
            toast = task and (f"Done: {task.text}" if task.done else f"Back on the list: {task.text}")
    except TasksFileError as e:
        await query.answer(f"{e}. Check it for a typo.", show_alert=True)
        return
    await query.answer(toast or "That task changed or was removed. Here's the current list.")
    try:
        await query.edit_message_reply_markup(today_buttons(today, evening=action != TASK_TAP))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def _set_commands(app: Application) -> None:
    """The menu Telegram shows when Ty types "/" (only in his chat)."""
    try:
        await app.bot.set_my_commands(
            [BotCommand("tasks", "Today's list; tap a task to check it off"),
             BotCommand("add", "Add a task (/add tomorrow ... for tomorrow only)"),
             BotCommand("phrase", "This week's phrase, slowly, with the spelling"),
             BotCommand("help", "What I can do")],
            scope=BotCommandScopeChat(int(app.bot_data["chat_id"])),
        )
    except TelegramError as e:
        log.warning("Couldn't set the command menu: %s", e)


def run_scheduler(config: dict, token: str, chat_id: str) -> None:
    app = Application.builder().token(token).post_init(_set_commands).build()
    app.bot_data.update(config=config, chat_id=chat_id)
    app.job_queue.run_repeating(check_schedule, interval=CHECK_EVERY_SECONDS, first=1)
    # Only Ty's chat counts: the bot's username is public, so messages from anyone else are ignored.
    # Edited messages are skipped too. Handlers are tried in order; the first match wins.
    ty = filters.Chat(chat_id=int(chat_id)) & filters.UpdateType.MESSAGE
    app.add_handler(CommandHandler("tasks", on_tasks, filters=ty))
    app.add_handler(CommandHandler("add", on_add, filters=ty))
    app.add_handler(CommandHandler("phrase", on_phrase, filters=ty))
    app.add_handler(CommandHandler(["help", "start"], on_help, filters=ty))
    app.add_handler(MessageHandler(ty & filters.COMMAND, on_unknown_command))
    app.add_handler(MessageHandler(ty, on_message))
    app.add_handler(CallbackQueryHandler(on_task_tap, pattern=f"^[{TASK_TAP}{EVENING_DONE}{EVENING_MOVE}{EVENING_DROP}]:"))
    schedule = config["schedule"]
    log.info("Coach running (%s). Mornings: %s on weekdays, %s on weekends. Midday %s (weekdays), evening %s.",
             config["timezone"], schedule["morning_weekdays"], schedule["morning_weekends"],
             schedule["midday"], schedule["evening"])
    app.run_polling()


async def send_now(config: dict, token: str, chat_id: str) -> None:
    async with Bot(token) as bot:
        await run_morning(config, bot, chat_id, datetime.now(ZoneInfo(config["timezone"])))


async def show_chat_ids(token: str) -> None:
    async with Bot(token) as bot:
        chats = await recent_chats(bot)
    if not chats:
        print("No messages yet. Send your bot any message in Telegram, then run this again.")
    for chat_id, name in chats.items():
        print(f"{name}: put TELEGRAM_CHAT_ID={chat_id} in .env")


class RedactingFormatter(logging.Formatter):
    """Masks the bot token anywhere in a log line, tracebacks included."""

    def __init__(self, fmt: str, secret: str):
        super().__init__(fmt)
        self.secret = secret

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return text.replace(self.secret, "[BOT TOKEN]") if self.secret else text


def setup_logging(token: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", token)
    handlers = [logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")]
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # otherwise it logs the check every minute


def main() -> None:
    parser = argparse.ArgumentParser(description="Coach: daily voice check-ins.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--now", action="store_true", help="send the morning briefing once, right away")
    mode.add_argument("--chat-id", action="store_true", help="show the chat ID for .env (message your bot first)")
    args = parser.parse_args()

    load_dotenv(PACKAGE_DIR.parent / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    setup_logging(token)
    sys.stdout.reconfigure(errors="replace")  # older Windows consoles can't print every accent
    config = load_config()

    try:
        if args.chat_id:
            if not token:
                raise SystemExit("Put TELEGRAM_BOT_TOKEN in .env first (see .env.example).")
            asyncio.run(show_chat_ids(token))
        elif args.now and token and chat_id:
            asyncio.run(send_now(config, token, chat_id))
            print("Sent to Telegram.")
        elif args.now:
            briefing, audio_path, _ = asyncio.run(prepare_morning(config, datetime.now(ZoneInfo(config["timezone"]))))
            print(briefing.text)
            print(f"\nAudio: {audio_path or 'none (the voice service did not answer)'}")
            print("Not sent: add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env to send it to Telegram.")
        elif token and chat_id:
            run_scheduler(config, token, chat_id)
        else:
            raise SystemExit("Scheduled mode needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env (see .env.example).")
    except Exception:
        # Logged through the redacting formatter so an error can never print the token.
        log.exception("Coach stopped with an error")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
