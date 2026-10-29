"""Sends the briefing to Telegram as one voice note, with the written copy as its caption,
and builds the buttons and the sports messages that go with it."""
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import MessageLimit

from coach.sources.sports import Game, Headline, clock, matchup, result
from coach.sources.tasks import Task, task_key

NO_VOICE_NOTE = "(No voice note today: the voice service didn't answer.)"
WAKE_BUTTON = "I'm up"
# Stays pinned under the chat, so a wake-day morning is one tap. Telegram keeps showing it
# once it's been sent, so it rides along on every message that doesn't carry task buttons.
KEYBOARD = ReplyKeyboardMarkup([[WAKE_BUTTON]], resize_keyboard=True, is_persistent=True)
# Button data is "<action>:<YYYY-MM-DD>:<task key>". The action also says which list to redraw.
TASK_TAP = "t"  # today's list (briefing, midday, /tasks): check off or back on
EVENING_DONE = "e"  # evening list: check off
EVENING_MOVE = "m"  # evening list: move to tomorrow
EVENING_DROP = "x"  # evening list: delete


def task_buttons(tasks: list[Task], day: date) -> InlineKeyboardMarkup | None:
    """One button per task; tapping it checks the task off, or back on. None if there are no tasks."""
    if not tasks:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(("✅ " if task.done else "⬜ ") + task.text, callback_data=_data(TASK_TAP, day, task))]
        for task in tasks
    ])


def evening_buttons(tasks: list[Task], day: date) -> InlineKeyboardMarkup | None:
    """For tasks still open in the evening: tap one to check it off. One-off tasks also get
    Tomorrow and Drop underneath. None once nothing is left open."""
    rows = []
    for task in tasks:
        if task.done:
            continue
        rows.append([InlineKeyboardButton("⬜ " + task.text, callback_data=_data(EVENING_DONE, day, task))])
        if not task.daily:
            rows.append([InlineKeyboardButton("↪ Tomorrow", callback_data=_data(EVENING_MOVE, day, task)),
                         InlineKeyboardButton("✕ Drop", callback_data=_data(EVENING_DROP, day, task))])
    return InlineKeyboardMarkup(rows) if rows else None


def _data(action: str, day: date, task: Task) -> str:
    return f"{action}:{day.isoformat()}:{task_key(task.text)}"


SPORT_ICONS = {"football": "🏈", "basketball": "🏀", "soccer": "⚽"}


def headlines_html(headlines: list[Headline]) -> str:
    """Stories about Ty's teams as a short message, each title a link. Telegram HTML."""
    items = [f"{escape(headline.team, quote=False)}: {_link(headline)}" for headline in headlines]
    return "<b>Sports headlines</b>\n\n" + "\n\n".join(items)


def sports_html(games: list[Game], headlines: list[Headline], now: datetime) -> str:
    """/sports: each team's next game and latest result (past week), then recent headlines. Telegram HTML."""
    if not games:
        return "Couldn't get your teams' games from ESPN right now. Try again in a bit."
    upcoming, latest = {}, {}
    for game in games:  # oldest first, so the first upcoming and the last finished game win
        if game.state in ("pre", "in") and game.team not in upcoming:
            upcoming[game.team] = game
        elif game.state == "post" and game.score and game.start >= now - timedelta(days=7):
            latest[game.team] = game
    sections = []
    if upcoming:
        lines = []
        for game in sorted(upcoming.values(), key=lambda g: g.start):
            when = "on now" if game.state == "in" else f"{game.start:%a %b} {game.start.day}, {clock(game.start)}"
            tv = f", {escape(game.tv, quote=False)}" if game.tv else ""
            lines.append(f"{_icon(game)} {escape(matchup(game, 'vs.'), quote=False)}: {when}{tv}")
        sections.append("<b>Next up</b>\n" + "\n".join(lines))
    if latest:
        lines = [f"{_icon(game)} {escape(result(game), quote=False)} ({game.start:%a})"
                 for game in sorted(latest.values(), key=lambda g: g.start, reverse=True)]
        sections.append("<b>Latest results</b>\n" + "\n".join(lines))
    if headlines:
        sections.append("<b>Headlines since yesterday</b>\n" + "\n".join(
            f"{escape(headline.team, quote=False)}: {_link(headline)}" for headline in headlines))
    else:
        sections.append("No new headlines about your teams since yesterday.")
    return "\n\n".join(sections)


def _icon(game: Game) -> str:
    return SPORT_ICONS.get(game.sport, "•")


def _link(headline: Headline) -> str:
    title = escape(headline.title, quote=False)  # only <, > and & need escaping in text
    return f'<a href="{escape(headline.url, quote=True)}">{title}</a>' if headline.url else title


async def send_briefing(bot: Bot, chat_id: int | str, text: str, audio_path: Path | None,
                        buttons: InlineKeyboardMarkup | None = None) -> None:
    """One message when possible. The text goes separately if it's too long for a caption.
    Task buttons go on whichever message holds the text."""
    markup = buttons or KEYBOARD
    if audio_path is None:
        await bot.send_message(chat_id, f"{NO_VOICE_NOTE}\n\n{text}", reply_markup=markup)
        return
    fits = len(text) <= MessageLimit.CAPTION_LENGTH
    with audio_path.open("rb") as audio:
        await bot.send_voice(chat_id, audio, caption=text if fits else None,
                             reply_markup=markup if fits else KEYBOARD)
    if not fits:
        await bot.send_message(chat_id, text, reply_markup=markup)


async def recent_chats(bot: Bot) -> dict[int, str]:
    """Chats that recently messaged the bot, as {chat_id: name}. Used once to find TELEGRAM_CHAT_ID."""
    chats = {}
    for update in await bot.get_updates():
        chat = update.effective_chat
        if chat:
            chats[chat.id] = chat.first_name or chat.title or chat.username or "unknown"
    return chats
