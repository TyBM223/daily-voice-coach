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
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.constants import ChatAction
from telegram.error import NetworkError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from coach.briefing import Briefing, build_briefing
from coach.delivery.telegram import KEYBOARD, recent_chats, send_briefing
from coach.sources.content import pick_content, pick_quote
from coach.sources.tasks import TasksFileError, load_tasks
from coach.sources.weather import fetch_weather
from coach.voice.tts import EdgeTTS, render

log = logging.getLogger("coach")

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
DATA_DIR = PACKAGE_DIR / "data"
AUDIO_PATH = DATA_DIR / "audio" / "morning.mp3"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "coach.log"

MORNING_GRACE = timedelta(hours=3)  # laptop asleep at 9:00? Still send if it wakes before noon
WAKE = "wake"  # morning setting in config.yaml: send when Ty says he's up
CHECK_EVERY_SECONDS = 60
SEND_ATTEMPTS = 3
RETRY_SECONDS = 20


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def prepare_morning(config: dict, now: datetime) -> tuple[Briefing, Path | None]:
    """Gather today's info, build the briefing, and save it as an MP3 (None if the voice fails)."""
    today = now.date()
    location = config["location"]
    weather = await asyncio.to_thread(
        fetch_weather, location["lat"], location["lon"], config["timezone"], config["temperature_unit"]
    )
    try:
        tasks = load_tasks(DATA_DIR / "tasks.json", today)
    except TasksFileError as e:
        log.warning("%s", e)
        tasks = None
    item = await asyncio.to_thread(pick_content, today, config["content_rotation"], config["language_to_learn"])
    briefing = build_briefing(config["owner_name"], location["name"], now, weather, tasks, item, pick_quote(today))

    try:
        audio = await render(briefing.segments, EdgeTTS(), config["voice"], config["phrase_voice"])
    except Exception as e:  # edge-tts fails in several ways; any of them means text only today
        log.warning("Voice unavailable, sending text only: %s", e)
        return briefing, None
    AUDIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIO_PATH.write_bytes(audio)
    return briefing, AUDIO_PATH


async def run_morning(config: dict, bot: Bot, chat_id: str, now: datetime) -> None:
    """Build today's briefing and send it, retrying if the network is briefly down."""
    briefing, audio_path = await prepare_morning(config, now)
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            await send_briefing(bot, chat_id, briefing.text, audio_path)
            log.info("Morning briefing sent")
            return
        except NetworkError as e:
            if attempt == SEND_ATTEMPTS:
                raise
            log.warning("Telegram send failed (%s); retrying in %s seconds", e, RETRY_SECONDS)
            await asyncio.sleep(RETRY_SECONDS)


def _morning_setting(schedule: dict, day: date) -> str:
    """config.yaml has one morning setting for weekdays and one for weekends: a time, or WAKE."""
    return schedule["morning_weekends" if day.weekday() >= 5 else "morning_weekdays"]


def morning_time(schedule: dict, day: date) -> time:
    """When the briefing goes out without a tap: the set time, or on wake days the fallback."""
    setting = _morning_setting(schedule, day)
    return time.fromisoformat(schedule["wake_latest"] if setting == WAKE else setting)


def wake_reply(sent_at: datetime, schedule: dict, last_sent: date | None) -> str | None:
    """Ty messaged the bot at sent_at. None means send today's briefing now; otherwise, a short reply."""
    if last_sent == sent_at.date():
        return "Today's briefing already went out. It's just above."
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


def morning_due(now: datetime, morning: time, last_sent: date | None, grace: timedelta = MORNING_GRACE) -> bool:
    """True if today's briefing hasn't gone out and it's between the morning time and the grace cutoff."""
    start = now.replace(hour=morning.hour, minute=morning.minute, second=0, microsecond=0)
    return last_sent != now.date() and start <= now < start + grace


def load_last_sent(path: Path = STATE_PATH) -> date | None:
    try:
        return date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["last_morning"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_last_sent(day: date | None, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_morning": day.isoformat() if day else None}), encoding="utf-8")


async def send_morning_once(config: dict, bot: Bot, chat_id: str, now: datetime) -> bool:
    """Send today's briefing. Today is claimed first, so the clock check and a tap can't both
    send it; if sending fails, the claim is undone so the next check or tap tries again."""
    last_sent = load_last_sent()
    save_last_sent(now.date())
    try:
        await run_morning(config, bot, chat_id, now)
        return True
    except Exception:
        log.exception("Morning briefing failed")
        save_last_sent(last_sent)
        return False


async def check_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute. Watching the clock, instead of one timer, means the briefing
    still goes out if the laptop was asleep or the coach restarted at the morning time."""
    config, chat_id = context.bot_data["config"], context.bot_data["chat_id"]
    now = datetime.now(ZoneInfo(config["timezone"]))
    if morning_due(now, morning_time(config["schedule"], now.date()), load_last_sent()):
        await send_morning_once(config, context.bot, chat_id, now)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A message from Ty. On wake days, the first one after wake_earliest sends the briefing."""
    config, chat_id = context.bot_data["config"], context.bot_data["chat_id"]
    tz = ZoneInfo(config["timezone"])
    message = update.effective_message
    sent_at = message.date.astimezone(tz)
    if sent_at.date() != datetime.now(tz).date():
        return  # sent before midnight and only picked up now because the laptop was asleep
    reply = wake_reply(sent_at, config["schedule"], load_last_sent())
    if reply:
        await message.reply_text(reply, reply_markup=KEYBOARD)
        return
    await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
    if not await send_morning_once(config, context.bot, chat_id, datetime.now(tz)):
        await message.reply_text("Something went wrong building your briefing. Tap again in a minute.",
                                 reply_markup=KEYBOARD)


def run_scheduler(config: dict, token: str, chat_id: str) -> None:
    app = Application.builder().token(token).build()
    app.bot_data.update(config=config, chat_id=chat_id)
    app.job_queue.run_repeating(check_morning, interval=CHECK_EVERY_SECONDS, first=1)
    # Only Ty's chat counts: the bot's username is public, so messages from anyone else are ignored.
    app.add_handler(MessageHandler(filters.Chat(chat_id=int(chat_id)) & filters.UpdateType.MESSAGE, on_message))
    schedule = config["schedule"]
    log.info("Coach running (%s). Mornings: %s on weekdays, %s on weekends.",
             config["timezone"], schedule["morning_weekdays"], schedule["morning_weekends"])
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
            briefing, audio_path = asyncio.run(prepare_morning(config, datetime.now(ZoneInfo(config["timezone"]))))
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
