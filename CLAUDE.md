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
  messages.py      understands plain-word messages ("done gym")
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
- Language to learn: Portuguese, Brazilian (Ty switched from Spanish on 2026-10-29; Brazilian chosen by default as the most widely spoken variant). The Spanish deck stays in the repo for anyone else.
- Voice notes are sent as MP3, no ffmpeg.
- The language phrase is spoken by a native voice (`phrase_voice` in config.yaml: pt-BR-AntonioNeural for Portuguese, es-MX-JorgeNeural for Spanish). The briefing is synthesized as separate clips and the MP3 bytes are joined; edge-tts output has no headers, so this is safe.
- httpx request logging is kept at WARNING because Telegram URLs contain the bot token. Every log line also goes through `RedactingFormatter`, because python-telegram-bot puts the token in some error messages. Logs go to the console and `data/coach.log`.
- Main voice: en-GB-RyanNeural (British, Ty's pick).
- Delivery: one Telegram message per briefing (voice note with the text as its caption; text goes separately only if it's over 1024 characters). If the voice fails, text only.
- Morning time: 9:00 on weekdays. Weekends are `wake` days, because Ty sleeps in with no alarm: the briefing goes out when he taps the pinned "I'm up" button (any message counts) after 6:00, or at noon if he hasn't. Telegram doesn't tell bots when a user is online, so a tap is the signal. Set in config.yaml (`morning_weekdays`, `morning_weekends`, `wake_earliest`, `wake_latest`); either day type can be a time or `wake`.
- The bot only listens to `TELEGRAM_CHAT_ID`; messages from anyone else are ignored (the bot's username is public). In v1, Ty's messages are only the wake signal; other replies are v3.
- Scheduling: a job checks the clock every minute instead of setting timers, so a laptop that was asleep at a check-in's time still sends when it wakes, up to 3 hours late. Applies to the morning, midday and evening slots; `data/state.json` keeps `last_morning`, `last_midday` and `last_evening`.
- Evening "Tomorrow" sets `"from": "YYYY-MM-DD"` on the task (and clears any date): hidden until then, shown every day after until it's done, so a moved task can't silently disappear. Daily tasks can't be moved or dropped from Telegram, so a stray tap can't delete a habit. `data/state.json` records the last date sent so restarts never double-send.
- `coach/data/tasks.json` format:
  ```json
  {"tasks": [
    {"text": "Gym", "repeat": "daily"},
    {"text": "Finish cover letter"},
    {"text": "Call mom", "date": "2026-10-30"}
  ]}
  ```
  `"repeat": "daily"` shows every day; no date shows every day until it's done or deleted; `"date"` shows only on that day.
- The bot edits tasks.json too (v2): `/add` appends a line, and checking a task off adds `"done": "YYYY-MM-DD"`. A daily task counts as done only on that date; any other task is hidden from the next day on and cleared out of the file on the next edit. The file keeps one task per line so it stays easy to edit by hand. Writes go through a temp file, and a file that can't be read is never overwritten.
- `data/log.json` records what got done each day (`{"YYYY-MM-DD": {"done": [...]}}`), for the evening recap and v3's streaks and weekly report. A damaged log is left alone, not overwritten.
- Task buttons are Telegram inline buttons with data `t:<date>:<12-char sha1 of the text>` (under the 64-byte limit). A tap on an earlier day's list is refused and points to `/tasks`. Messages without task buttons carry the "I'm up" keyboard, which Telegram keeps showing.
- Content rotation: Mon phrase, Tue fact, Wed history, Thu joke, Fri review of Monday's phrase, weekends rotate fact / history / joke.
- Picks come from what's been sent (v2): every morning briefing records its phrase / fact / history / joke and quote under `"sent"` in `data/log.json`, only after it actually goes out. Each deck is walked in order, skipping anything sent; once a deck is used up, the one heard longest ago comes back first. JokeAPI is asked up to 3 times for a joke not told before; Wikipedia events already told are skipped. New deck entries just get their turn. Reviews aren't recorded, so they don't move a phrase's review schedule.
- Phrase reviews only cover phrases Ty actually heard: Friday's morning slot reviews the newest phrase from the past 6 days (or becomes a fun fact if there isn't one), and the evening check-in adds a quick review 1, 3 and 7 days after a phrase is taught. `/phrase` resends the latest phrase word by word and slowly, then at normal speed, with the spelling.
- Sports source: ESPN's public site JSON (Ty's pick, 2026-10-29), no key or account. Teams live in config.yaml (`teams`: name, ESPN team ID, ESPN league paths, optional headline keywords). Headlines are matched on the team's name as a case-sensitive whole word, so "heat wave" doesn't count; video clips are skipped. The headlines message is sent after the briefing and never raises, so a failure there can't make the briefing resend.
- Closing quote: curated `quotes.json` (Ty's pick over a quotes API), a new one each day (picked like the decks above), attributions checked by hand. Quotes stay at 22 words or fewer so the busiest briefing fits in 75 seconds; if the file can't be read, the briefing ends with a plain sign-off.

## Roadmap

### v1: Morning briefing (MVP)
- [x] Fetch weather (current temp, high/low, rain chance, short summary)
- [x] Load today's tasks from `data/tasks.json`
- [x] Pick the daily content item from the weekday rotation (grim Wikipedia events skipped)
- [x] Build the script from a template (~45-75 sec spoken). Casual, direct, encouraging, not cheesy
- [x] Convert to audio with edge-tts (phrase in a native voice, clips joined)
- [x] "Top priority" line (first one-off task) and a slowed-down second repeat of the phrase
- [x] Briefing ends on a new quote each day (`content_data/quotes.json`) instead of a fixed sign-off
- [x] Weekend briefing waits for Ty's "I'm up" tap, with a noon fallback (built and unit-tested; waiting on a live weekend)
- [x] Send voice note + text version to Telegram (first live send 2026-10-29)
- [x] `--now` runs it once immediately (`--chat-id` finds the chat ID)
- [ ] Scheduled run at the morning time (built; waiting on a live morning)

Done when Ty gets a voice note every morning without touching anything.

### v2: Check-ins + memory (started 2026-10-29)
Order Ty approved: 1. tasks from Telegram, 2. midday + evening check-ins, 3. phrase help + no repeats, 4. sports. Checkpoint after each group.
Check-in style: midday is text only (with task buttons); the evening is a short voice note + text.
- [x] Group 1: today's tasks as buttons on the briefing and on `/tasks` (tap to check off, tap again to undo); `/add <task>` and `/add tomorrow <task>`; `/help` and a "/" command menu (built and tested with stand-in messages; waiting on a live try)
- [x] Group 2: midday check-in at 12:30 on weekdays (one line on what's left, with task buttons; skipped when there are no tasks) and an evening wrap-up at 6:00 PM every day (short voice note: what got done, what's open, tomorrow's weather and first task; open tasks get Done buttons, and one-offs also get Tomorrow / Drop). Built and dry-run against the real task list; waiting on a live evening
- [x] Group 3: no repeats (phrases, facts, history, jokes and quotes picked from the sent history in `data/log.json`); spaced phrase reviews in the evening 1, 3 and 7 days after a phrase is taught; `/phrase` resends the latest phrase word by word, slowly, then at normal speed, with the spelling. Built and dry-run; waiting on a live week
- [ ] Optional (ask first): top news headlines from free RSS feeds (no key), in the briefing or on `/news`
- [x] Group 4: sports for Ty's teams (49ers, Heat, Auburn football, Chelsea incl. League Cup and FA Cup; no hockey or baseball). The morning briefing says yesterday's results and today's games with time and TV (game-day mornings can run to about 86 seconds); up to 3 headlines from the last 24 hours follow as a short text with links; `/sports` shows next games, results from the past week and headlines since yesterday. Built and dry-run with live data; waiting on a live game day
- [ ] Optional (ask first): sync with a free task app (Google Tasks API)
- [ ] Optional (ask first): Ollama-generated briefing script

### v3: Talk back (started 2026-10-29)
Order Ty approved: 1. plain-word replies, 2. streaks + Sunday report, 3. voice notes in (faster-whisper, ask before installing), 4. questions about the day (local hermes3, already installed; runs 100% on the RX 6700S at ~32 tokens/s, ~20 s to load cold). Checkpoint after each group.
- [x] Group 1: plain-word replies without AI (`coach/messages.py`): done / undo / move / drop / add / what's left / help / thanks, several tasks at once ("done gym and applications"), loose matching on part of a task's name, a question back with buttons when it's a toss-up, and no action on questions ("did you see the game?"). Daily habits can't be moved or dropped, and finished tasks aren't reopened. On wake days a request also counts as "I'm up". Built and dry-run; waiting on live use
- [ ] Voice replies transcribed locally with faster-whisper
- [ ] Questions about the day's content, by text or voice ("how do you spell that?", "say it slower", "tell me more about that history fact"). Answers come from local Ollama, grounded in the Wikipedia article so it doesn't make things up
- [ ] Streaks per recurring goal (gym, applications, project hours, social plans)
- [ ] Evening check-in asks about unfinished tasks and records the answer
- [ ] Weekly Sunday report: completion rate, streaks, wins
- [ ] Tone: honest. If things slipped, say so plainly and help re-plan; no guilt-trips, no sugarcoating

### v4: Conversation (checkpoint before starting)
- [ ] Morning opens with a question ("Morning, Ty. How'd you sleep?"). Ty's reply (voice or text) gets a short, genuine response, then the briefing. If there's no reply within a set time, the briefing goes out anyway, so the morning never depends on answering
- [ ] Open back-and-forth by voice note: ask about the news so far today, the history fact, the task list, anything. Spoken answers from local Ollama + faster-whisper + edge-tts, all free
- [ ] News questions answered from free RSS headlines, not from the model's memory
- [ ] Remembers what Ty said earlier in the day (stored in `data/`) so replies stay in context
- Limits: Telegram bots can't take live calls, so this is voice-note back-and-forth, and each reply takes several seconds to tens of seconds on a laptop. A live, talk-over-each-other conversation would need a different setup (a local app); explore only if Ty wants it later. Paid real-time voice APIs are out (Rule 1).

### Deployment (checkpoint required)
Start by running locally. Always-on options to discuss later: keep the home PC running, an old laptop/phone as a mini server, or a free cloud tier. Many "free" cloud tiers need a credit card: flag that, and don't sign up for anything without Ty's OK.
- [x] Chosen 2026-10-29 (Ty's OK): the laptop, started at login by a shortcut in Ty's Startup folder (`Coach (Myles).lnk` → `.venv\Scripts\pythonw.exe -m coach.main`, start in the repo). No admin needed; delete the shortcut to undo. Task Scheduler was the alternative (it can restart after a crash, but a logon task needs admin).
- [x] Code for it: runs with no window (logs only to `data/coach.log`), keeps retrying if Wi-Fi isn't up at login (`bootstrap_retries=-1`), and holds `data/coach.lock` so a second copy quits instead of double-sending
- [x] Ty set Windows to never sleep while plugged in (2026-10-29; he changes system settings himself). Auto-started copy confirmed answering `/tasks` the same day.
- Limit: the coach runs only while Ty is signed in. After an overnight update restart it starts at sign-in, and the 3-hour window covers a late morning.
- Later, if Ty wants the laptop free: an old phone or a Raspberry Pi as an always-on box.

## Known free-tier risks
- edge-tts uses Microsoft's public endpoint and could break. Fallback: Piper.
- JokeAPI / Wikipedia could rate-limit or go down. Always fall back to local JSON.
- ESPN's site JSON (sports) is public but unofficial and undocumented, so it can change or go away without notice. Every sports call fails soft: no sports line or headlines that day, the rest of the briefing unaffected. Backup if it breaks: TheSportsDB's free key (one upcoming game per team, no TV channels or news).
- Ollama needs decent RAM/CPU. Ty's laptop (checked 2026-10-28): Ryzen 9 6900HS, 16 GB RAM, AMD RX 6700S with 8 GB, Ollama 0.40.8 installed. Before v3, check whether Ollama actually uses the AMD GPU; on CPU alone, expect slower replies and stick to small models.
