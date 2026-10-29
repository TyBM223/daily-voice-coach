# Coach

A free, self-hosted voice assistant that checks in through the day on Telegram: date, weather, today's tasks, a daily joke, fun fact, history moment or foreign-language phrase, and a quote to close it out. It's built for accountability: a coach checking in, not notification spam.

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
   - A day set to `wake` (weekends, by default) has no set time: the briefing comes when you tap the "I'm up" button under the chat (any message works), or at `wake_latest` if you don't.
   - The bot only answers your own chat, so it's fine that its username is public.
9. Start it automatically when you sign in (Windows), so there's no window to keep open:
   - Press Win+R, type `shell:startup`, and press Enter.
   - In that folder, right-click → New → Shortcut. For the location, enter the full path to `.venv\Scripts\pythonw.exe` in this folder, followed by ` -m coach.main`. Name it "Coach".
   - Right-click the shortcut → Properties, and set "Start in" to this folder.
   - `pythonw` runs it with no window; everything goes to `coach/data/coach.log`. Only one copy runs at a time, so starting it twice is harmless. To stop it, end `pythonw.exe` in Task Manager. To turn auto-start off, delete the shortcut.
   - Set Windows to never sleep while plugged in (Settings → System → Power & battery), or check-ins wait until the computer wakes (up to 3 hours late).

## Using it from Telegram

- Today's tasks come as buttons under the briefing. Tap one to check it off; tap again to undo.
- `/tasks` shows today's list, with the same buttons.
- `/add Finish resume` adds a task that stays until it's done. `/add tomorrow Call mom` adds one for tomorrow only.
- `/phrase` resends the latest language phrase word by word, slowly, then at normal speed, with the spelling written out.
- `/sports` shows your teams' next games (time and TV), results from the past week, and headlines since yesterday.
- `/help` lists everything.
- Or just type: `done gym`, `done gym and applications`, `push resume to tomorrow`, `drop the walk`, `add call recruiter tomorrow`, `what's left`. Part of a task's name is enough; if two tasks fit, the bot asks which.
- At 12:30 on weekdays, a one-line midday check shows what's left, with the same buttons.
- At 6:00 PM, a short voice note recaps the day and previews tomorrow (weather and first task). Anything still open gets buttons: check it off, move it to tomorrow, or drop it.

Check-offs are saved in `coach/data/tasks.json` and logged by day in `coach/data/log.json`. You can still edit `tasks.json` by hand. The log also records what each briefing said, so facts, jokes, history moments, phrases and quotes don't repeat until a deck is used up, and phrase reviews only cover phrases you've heard.

## Sports

Set your teams under `teams:` in `coach/config.yaml`: a name, the ESPN team ID (the number in the team's espn.com URL), and ESPN's league paths (for example `basketball/nba`, `football/nfl`, `football/college-football`, `soccer/eng.1`). On game days the morning briefing mentions the game, time and channel; the morning after, the score. Up to three headlines about your teams follow the briefing as a short text. The data comes from ESPN's public site feeds, which are free but unofficial, so if they change, the sports parts are skipped and everything else still works.

## License

MIT. See [LICENSE](LICENSE).
