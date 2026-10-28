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
3. Copy `.env.example` to `.env` and fill in your Telegram bot token and chat ID.
4. Edit `coach/config.yaml` for your name, city, time zone and schedule.
5. Run the tests: `.venv\Scripts\python -m pytest`
