"""Sends the briefing to Telegram as one voice note, with the written copy as its caption,
and builds the buttons that go with it."""
from datetime import date
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import MessageLimit

from coach.sources.tasks import Task, task_key

NO_VOICE_NOTE = "(No voice note today: the voice service didn't answer.)"
WAKE_BUTTON = "I'm up"
# Stays pinned under the chat, so a wake-day morning is one tap. Telegram keeps showing it
# once it's been sent, so it rides along on every message that doesn't carry task buttons.
KEYBOARD = ReplyKeyboardMarkup([[WAKE_BUTTON]], resize_keyboard=True, is_persistent=True)
TASK_TAP = "t"  # task button data: "t:<YYYY-MM-DD>:<task key>"


def task_buttons(tasks: list[Task], day: date) -> InlineKeyboardMarkup | None:
    """One button per task; tapping it checks the task off, or back on. None if there are no tasks."""
    if not tasks:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(("✅ " if task.done else "⬜ ") + task.text,
                              callback_data=f"{TASK_TAP}:{day.isoformat()}:{task_key(task.text)}")]
        for task in tasks
    ])


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
