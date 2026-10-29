# Coach: daily voice assistant

A personal assistant that checks in with Ty by voice through the day: date, time, Tampa weather, today's tasks, and a daily joke / fun fact / history lesson / foreign-language phrase. Main purpose: accountability. It should feel like a coach checking in, not a notification spam bot.

- Owner: Ty, Tampa, FL (America/New_York). Goals: job search, projects, gym.
- Delivery: Telegram voice note + text copy, on Ty's phone.
- The repo will be public (others can use it; Ty may use it on his resume), so keep personal data out of committed files.

## Hard rules (read before every task)

### 1. 100% free
- No paid subscriptions, no pay-as-you-go APIs, no "free trial then billing", no services that need a credit card on file.
- Free tiers are OK only if they need no card and can't auto-upgrade to paid.
- If a feature can't move forward without paying: STOP. Tell Ty what's blocked and why, then ask permission to search GitHub for open-source alternatives. Don't search or swap tools until he says yes. When reporting options, include repo link, stars, last commit date, license, and whether it runs locally.
- The coach must run on its own. Never make it depend on Claude, Claude plugins/connectors, or Claude scheduled tasks.

### 2. Ty stays in the loop
Stop and check in (short summary + question) at each of these:
- Before starting any version (v1/v2/v3) or major feature: share the plan, wait for "go".
- Before any hard-to-reverse or architecture decision: library choice, storage format, new dependency, file structure change.
- When blocked: errors not fixed in 2 tries, API limits, missing access, unclear requirements. Explain plainly, give options, recommend one.
- After finishing each checklist group: what was built, what was tested, what's next.
- Before installing system-level software, creating accounts, or touching anything outside the project folder.

### 3. Don't overreach
- Do only what the current step asks. No bonus features, no "while I'm in here" refactors without asking.
- Prefer small steps Ty can review over big batches.
- Never commit `.env` or `data/`. Never put secrets in code or logs.

## Checkpoint format

```
CHECKPOINT: <what stage>
Done: <bullets>
Decision/obstacle: <what needs Ty's input>
Options: <A / B, with tradeoffs>
My recommendation: <one>
Waiting on: <exactly what you need from Ty>
```

## Stack (all free)
- Python 3.13 in `.venv`.
- Weather: Open-Meteo (no key, no card).
- Voice (TTS): `edge-tts`, behind the interface in `coach/voice/tts.py`. Fallback if it breaks: Piper (local).
- Daily content: JokeAPI (safe mode) and Wikipedia "On This Day", both falling back to local JSON. Facts and language phrases come from curated JSON in `coach/content_data/`.
- LLM (optional, v2+): local Ollama only. The template script is the default; Ollama is never required.
- Delivery: `python-telegram-bot`. Voice notes go out as MP3 (Telegram's sendVoice accepts OGG/Opus, MP3 or M4A), so no ffmpeg is needed.
- Scheduling: APScheduler 3.x through python-telegram-bot's `job-queue` extra, so the same process can receive Ty's replies in v3.
- Storage: local JSON in `coach/data/` (gitignored).
- Speech-to-text (v3): `faster-whisper`, local.
- Secrets in `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## Layout
```
coach/
  main.py          entrypoint
  config.yaml      times, location, language, voice, content rotation
  briefing.py      builds the spoken script
  sources/         weather.py, tasks.py, content.py
  voice/tts.py
  delivery/telegram.py
  content_data/    curated facts, phrases, jokes (committed)
  data/            tasks.json, generated audio, history (gitignored)
tests/
```

## Commands (from the repo root)
- Run once now: `.venv\Scripts\python -m coach.main --now`
- Run on schedule: `.venv\Scripts\python -m coach.main`
- Tests: `.venv\Scripts\python -m pytest`

## Decisions made
- Project lives in `Documents\coach` on Windows, not WSL (WSL shuts down when idle).
- Language to learn: Spanish (placeholder; Ty may change it).
- Voice notes are sent as MP3, no ffmpeg.
- The language phrase is spoken by a native voice (`phrase_voice` in config.yaml, es-MX-JorgeNeural for Spanish). The briefing is synthesized as separate clips and the MP3 bytes are joined; edge-tts output has no headers, so this is safe.
- httpx request logging is kept at WARNING because Telegram URLs contain the bot token.
- `coach/data/tasks.json` format:
  ```json
  {"tasks": [
    {"text": "Gym", "repeat": "daily"},
    {"text": "Finish cover letter"},
    {"text": "Call mom", "date": "2026-10-30"}
  ]}
  ```
  `"repeat": "daily"` shows every day; no date shows every day until deleted; `"date"` shows only on that day.
- Content rotation: Mon phrase, Tue fact, Wed history, Thu joke, Fri review of Monday's phrase, weekends rotate fact / history / joke. In v1 picks come from the date, so nothing is stored.

## Roadmap

### v1: Morning briefing (MVP)
- [x] Fetch weather (current temp, high/low, rain chance, short summary)
- [x] Load today's tasks from `data/tasks.json`
- [x] Pick the daily content item from the weekday rotation (grim Wikipedia events skipped)
- [x] Build the script from a template (~45-75 sec spoken). Casual, direct, encouraging, not cheesy
- [x] Convert to audio with edge-tts (phrase in a native voice, clips joined)
- [ ] Send voice note + text version to Telegram
- [ ] `--now` runs it once immediately
- [ ] Scheduled run at the morning time

Done when Ty gets a voice note every morning without touching anything.

### v2: Check-ins + memory (checkpoint before starting)
- [ ] Midday check-in: what's left today
- [ ] Evening wrap-up: recap the day, preview tomorrow
- [ ] Phrase memory: never repeat a new phrase; spaced review after 1, 3, 7 days
- [ ] No repeated facts/jokes (history log)
- [ ] Add tasks from Telegram: `/add <task>`
- [ ] Optional (ask first): sync with a free task app (Google Tasks API)
- [ ] Optional (ask first): Ollama-generated briefing script

### v3: Talk back (checkpoint before starting)
- [ ] Telegram commands + natural replies ("done gym", "push resume to tomorrow")
- [ ] Voice replies transcribed locally with faster-whisper
- [ ] Streaks per recurring goal (gym, applications, project hours, social plans)
- [ ] Evening check-in asks about unfinished tasks and records the answer
- [ ] Weekly Sunday report: completion rate, streaks, wins
- [ ] Tone: honest. If things slipped, say so plainly and help re-plan; no guilt-trips, no sugarcoating

### Deployment (checkpoint required)
Start by running locally. Always-on options to discuss later: keep the home PC running, an old laptop/phone as a mini server, or a free cloud tier. Many "free" cloud tiers need a credit card: flag that, and don't sign up for anything without Ty's OK.

## Known free-tier risks
- edge-tts uses Microsoft's public endpoint and could break. Fallback: Piper.
- JokeAPI / Wikipedia could rate-limit or go down. Always fall back to local JSON.
- Ollama needs decent RAM/CPU. Check the machine before relying on it.
