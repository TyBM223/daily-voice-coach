# Coach

A free, self-hosted voice assistant that checks in through the day on Telegram: date, weather, today's tasks, and a daily joke, fun fact, history moment or foreign-language phrase. It's built for accountability: a coach checking in, not notification spam.

Everything runs on free tools with no paid APIs and no credit card: Open-Meteo for weather, edge-tts for the voice, Wikipedia and JokeAPI for content, and a Telegram bot for delivery.

**Status:** v1 (morning briefing) is in progress.

## Setup (Windows)

1. Install Python 3.11 or newer.
2. Create a virtual environment and install packages:
   ```
   py -3.13 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Set up Telegram:
   - In Telegram, message @BotFather, send `/newbot`, and copy the token it gives you.
   - Copy `.env.example` to `.env` and paste the token after `TELEGRAM_BOT_TOKEN=`.
   - Send your new bot any message, then run `.venv\Scripts\python -m coach.main --chat-id` and put the number it prints after `TELEGRAM_CHAT_ID=`.
4. Edit `coach/config.yaml` for your name, city, time zone, schedule and voices.
5. Copy `coach/tasks.example.json` to `coach/data/tasks.json` and put in your own tasks:
   - `"repeat": "daily"` shows every day
   - no date shows every day until you delete it
   - `"date": "YYYY-MM-DD"` shows only on that day
6. Run the tests: `.venv\Scripts\python -m pytest`
7. Send a briefing right now: `.venv\Scripts\python -m coach.main --now`. Without Telegram set up, it prints the briefing and saves the MP3 to `coach/data/audio/` instead.
8. Run it for real: `.venv\Scripts\python -m coach.main`. Leave it running and the briefing arrives every morning at the time in `config.yaml`. If the computer was asleep then, it goes out as soon as it wakes, up to three hours late.

## License

MIT. See [LICENSE](LICENSE).
