"""Sends the briefing to Telegram as one voice note, with the written copy as its caption."""
from pathlib import Path

from telegram import Bot
from telegram.constants import MessageLimit

NO_VOICE_NOTE = "(No voice note today: the voice service didn't answer.)"


async def send_briefing(bot: Bot, chat_id: int | str, text: str, audio_path: Path | None) -> None:
    """One message when possible. The text goes separately if it's too long for a caption."""
    if audio_path is None:
        await bot.send_message(chat_id, f"{NO_VOICE_NOTE}\n\n{text}")
        return
    fits = len(text) <= MessageLimit.CAPTION_LENGTH
    with audio_path.open("rb") as audio:
        await bot.send_voice(chat_id, audio, caption=text if fits else None)
    if not fits:
        await bot.send_message(chat_id, text)


async def recent_chats(bot: Bot) -> dict[int, str]:
    """Chats that recently messaged the bot, as {chat_id: name}. Used once to find TELEGRAM_CHAT_ID."""
    chats = {}
    for update in await bot.get_updates():
        chat = update.effective_chat
        if chat:
            chats[chat.id] = chat.first_name or chat.title or chat.username or "unknown"
    return chats
