"""Builds what the coach says: the morning briefing, the evening wrap-up and /phrase help (each
a spoken script split into voice segments, plus a written copy), and the one-line midday check-in."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from coach.progress import Week
from coach.sources.content import ContentItem, Fact, HistoryMoment, Joke, Phrase, Quote
from coach.sources.sports import Game, clock, matchup, result
from coach.sources.tasks import Task
from coach.sources.weather import Weather

MAX_SPOKEN_TASKS = 5
EVENING_SPOKEN_TASKS = 3  # the evening recap names fewer; the buttons list the rest
FALLBACK_SIGN_OFF = "That's the rundown. Go get it."  # only if quotes.json can't be read


@dataclass
class Segment:
    text: str
    foreign: bool = False  # spoken by the phrase voice, in the language being learned
    slow: bool = False  # spoken slower, so a new phrase is easy to make out


@dataclass
class Briefing:
    segments: list[Segment]
    text: str  # written copy sent with the voice note


class _Script:
    """Collects spoken lines, merging consecutive English lines into one segment."""

    def __init__(self):
        self.segments: list[Segment] = []

    def say(self, text: str, *, foreign: bool = False, beat: bool = False, slow: bool = False) -> None:
        """beat=True starts a new segment, which leaves a short pause before it."""
        last = self.segments[-1] if self.segments else None
        if last and not last.foreign and not last.slow and not foreign and not beat and not slow:
            last.text += " " + text
        else:
            self.segments.append(Segment(text, foreign, slow))


def build_briefing(
    name: str,
    place: str,
    now: datetime,
    weather: Weather | None,
    tasks: list[Task] | None,
    item: ContentItem,
    quote: Quote | None,
    games: list[Game] = (),
) -> Briefing:
    """Assemble the briefing. tasks is None when tasks.json couldn't be read; quote, when quotes.json couldn't.
    games are the teams' listed games; only today's and yesterday's are mentioned."""
    script = _Script()
    written = [
        _greeting(script, name, now),
        _weather(script, weather, place),
        _tasks(script, tasks),
        _content(script, item),
        _sports(script, games, now),
        _closing(script, quote),
    ]
    return Briefing(script.segments, "\n\n".join(line for line in written if line))


def _sports(script: _Script, games: list[Game], now: datetime) -> str:
    """Yesterday's results, then today's games: "Last night: Heat beat Hawks, 129 to 117. Game day:
    Heat versus Pacers, 8 PM, on NBA League Pass." Nothing on days without games."""
    today, yesterday = now.date(), now.date() - timedelta(days=1)
    games = sorted(games, key=lambda game: game.start)
    lines = []
    finished = [game for game in games if game.state == "post" and game.score
                and game.start.date() in (yesterday, today)]
    for game in finished:
        when = "Earlier today" if game.start.date() == today else "Last night" if game.start.hour >= 17 else "Yesterday"
        lines.append(f"{when}: {result(game)}.")
    live = [game for game in games if game.state == "in" and game.start.date() == today]
    for game in live:
        lines.append(f"{matchup(game)} is on now" + (f" on {game.tv}." if game.tv else "."))
    upcoming = [game for game in games if game.state == "pre" and game.start.date() == today]
    if upcoming:
        lines.append("Game day: " + _join([f"{matchup(game)}, {clock(game.start)}{_on(game)}" for game in upcoming]) + ".")
    if not lines:
        return ""
    script.say(" ".join(lines))
    return "Sports: " + " ".join(lines)


def _on(game: Game) -> str:
    return f", on {game.tv}" if game.tv else ""


def _greeting(script: _Script, name: str, now: datetime) -> str:
    when = f"{now:%A, %B} {now.day}, {now:%I:%M %p}".replace(" 0", " ")
    script.say(f"Morning, {name}. It's {when}.")
    return f"Morning, {name}. {when}."


def _weather(script: _Script, weather: Weather | None, place: str) -> str:
    if weather is None:
        script.say("I couldn't get the weather this morning.")
        return "Weather: unavailable this morning."
    script.say(
        f"Weather in {place}: {weather.summary}, {weather.current_temp} degrees right now. "
        f"High of {weather.high}, low of {weather.low}. {_rain(weather.rain_chance)}"
    )
    return (
        f"Weather: {weather.summary.capitalize()}, {weather.current_temp}° now. "
        f"High {weather.high}°, low {weather.low}°. {weather.rain_chance}% chance of rain."
    )


def _rain(chance: int) -> str:
    if chance < 10:
        return "Rain's not a factor today."
    if chance < 40:
        return f"Rain chance is {chance} percent."
    if chance < 70:
        return f"Rain chance is {chance} percent, so keep an umbrella handy."
    return f"Rain chance is {chance} percent. Bring an umbrella."


def _tasks(script: _Script, tasks: list[Task] | None) -> str:
    if tasks is None:
        script.say("Heads up: I couldn't read your task file. Check tasks.json for a typo.")
        return "Tasks: couldn't read tasks.json. Check it for a typo."
    if not tasks:
        script.say("Nothing on your list today. Pick one thing that moves you forward and get it done.")
        return "Today: nothing on the list. Pick one thing that moves you forward."

    texts = [task.text for task in tasks]
    written = "Today:\n" + "\n".join(f"- {text}" for text in texts)
    if len(tasks) == 1:
        script.say(f"One thing on your list today: {_bare(texts[0])}.")
        return written

    spoken = [_bare(text) for text in texts[:MAX_SPOKEN_TASKS]]
    extra = len(texts) - len(spoken)
    if extra:
        spoken.append(f"{extra} more")
    script.say(f"You've got {len(texts)} things on your list: {_join(spoken)}.")

    # The first one-off task is the day's priority; daily habits are routine.
    priority = next((task.text for task in tasks if not task.daily), None)
    if priority:
        script.say(f"Top priority: {_bare(priority)}. Knock that out first.")
        written += f"\nTop priority: {priority}"
    return written


def _content(script: _Script, item: ContentItem) -> str:
    match item:
        case Phrase(review=False):
            note = f" {item.note}" if item.note else ""
            script.say(f"Your {item.language} phrase of the week:")
            script.say(item.phrase, foreign=True)
            script.say(f"It means: {item.meaning}{note} One more time, slowly:")
            script.say(item.phrase, foreign=True, slow=True)
            return f"{item.language} phrase of the week: {item.phrase}\nIt means: {item.meaning}{note}"
        case Phrase(review=True):
            script.say(f"Quick {item.language} review from earlier this week. Remember this one?")
            script.say(item.phrase, foreign=True)
            script.say(f"It means: {item.meaning}")
            return f"{item.language} review: {item.phrase}\nIt means: {item.meaning}"
        case Fact():
            script.say(f"Fun fact: {item.text}")
            return f"Fun fact: {item.text}"
        case HistoryMoment(year=None):
            script.say(f"A bit of history: {item.text}")
            return f"A bit of history: {item.text}"
        case HistoryMoment():
            line = f"On this day in {_year(item.year)}: {item.text}"
            script.say(line)
            return line
        case Joke(punchline=None):
            script.say(f"Joke of the day: {item.setup}")
            return f"Joke of the day: {item.setup}"
        case Joke():
            script.say(f"Joke of the day: {item.setup}")
            script.say(item.punchline, beat=True)
            return f"Joke of the day: {item.setup}\n{item.punchline}"
    raise TypeError(f"Unknown content item: {item!r}")


def _closing(script: _Script, quote: Quote | None) -> str:
    if quote is None:
        script.say(FALLBACK_SIGN_OFF)
        return FALLBACK_SIGN_OFF
    script.say(f"One for the road: {quote.text} That's {quote.author.rstrip('.')}.")
    return f'One for the road: "{quote.text}" — {quote.author}'


def build_midday(tasks: list[Task]) -> str | None:
    """The midday check-in: one short line on what's left. None when there's nothing to check on."""
    if not tasks:
        return None
    done = [task for task in tasks if task.done]
    left = [task for task in tasks if not task.done]
    if not left:
        return "Midday check: everything's checked off already. Nice work."
    if not done:
        return f"Midday check: nothing checked off yet. Still to do: {_names(left)}."
    return f"Midday check: {len(done)} done, {len(left)} to go: {_names(left)}."


def build_evening(
    name: str,
    tasks: list[Task] | None,
    tomorrow_weather: Weather | None,
    tomorrow_tasks: list[Task] | None,
    review: Phrase | None = None,
    streaks: dict[str, int] | None = None,
    week: Week | None = None,
) -> Briefing:
    """The evening wrap-up: how today went and any streaks, the week on Sundays (week is given),
    a quick phrase review on review days, then a look at tomorrow. About 20-30 seconds, longer on
    Sundays. tasks / tomorrow_tasks are None when tasks.json couldn't be read. streaks maps each
    daily task to its run of days (see progress.streak)."""
    script = _Script()
    script.say(f"Evening, {name}.")
    written = [f"Evening, {name}.", _recap(script, tasks)]
    if week:
        written.append(_week(script, week))  # it names the best streak, so the daily streak lines can rest
    else:
        written.append(_streak_lines(script, tasks, streaks or {}))
    if review:
        written.append(_evening_review(script, review))
    written.append(_tomorrow(script, tomorrow_weather, tomorrow_tasks))
    closing = _week_verdict(week) if week else _evening_closing(tasks)
    script.say(closing)
    written.append(closing)
    return Briefing(script.segments, "\n\n".join(line for line in written if line))


def _recap(script: _Script, tasks: list[Task] | None) -> str:
    if tasks is None:
        script.say("I couldn't read your task file, so no recap tonight. Check tasks.json for a typo.")
        return "Today: couldn't read tasks.json. Check it for a typo."
    if not tasks:
        script.say("No tasks on the list today.")
        return "Today: no tasks on the list."
    done = [task for task in tasks if task.done]
    left = [task for task in tasks if not task.done]
    if not left:
        script.say(f"You got everything done today: {_names(done, EVENING_SPOKEN_TASKS)}. Clean sweep.")
    elif not done:
        script.say(f"Nothing checked off today. Still open: {_names(left, EVENING_SPOKEN_TASKS)}.")
    else:
        script.say(f"You got {len(done)} of {len(tasks)} done today: {_names(done, EVENING_SPOKEN_TASKS)}. "
                   f"Still open: {_names(left, EVENING_SPOKEN_TASKS)}.")
    if left:
        move = " Anything else can move to tomorrow." if any(not task.daily for task in left) else ""
        script.say(f"If you finished any of those, tap them off.{move}")
    checklist = "\n".join(("✅ " if task.done else "⬜ ") + task.text for task in tasks)
    return f"Today: {len(done)} of {len(tasks)} done\n{checklist}"


def _tomorrow(script: _Script, weather: Weather | None, tasks: list[Task] | None) -> str:
    written = []
    if weather is None:
        script.say("I couldn't get tomorrow's forecast.")
        written.append("Tomorrow: forecast unavailable.")
    else:
        script.say(f"Tomorrow: {weather.summary}, high of {weather.high}, low of {weather.low}. {_rain(weather.rain_chance)}")
        written.append(f"Tomorrow: {weather.summary.capitalize()}, high {weather.high}°, low {weather.low}°. "
                       f"{weather.rain_chance}% chance of rain.")
    first = next((task.text for task in tasks or [] if not task.daily), None)
    if first:
        script.say(f"First up: {_bare(first)}.")
        written.append(f"First up: {first}")
    return "\n".join(written)


def _streak_lines(script: _Script, tasks: list[Task] | None, streaks: dict[str, int]) -> str:
    """"That's 4 days straight on Gym." / "Gym is still open, with a 4-day streak on the line."
    Only runs of 2 days or more are worth a mention."""
    daily = [(task, streaks.get(task.text, 0)) for task in tasks or [] if task.daily]
    going = [(task, days) for task, days in daily if task.done and days >= 2]
    on_the_line = [(task, days) for task, days in daily if not task.done and days >= 2]
    lines = []
    if len(going) == 1:
        lines.append(f"That's {going[0][1]} days straight on {_bare(going[0][0].text)}.")
    elif going:
        lines.append("Streaks going: " + _join([f"{days} days on {_bare(task.text)}" for task, days in going]) + ".")
    for task, days in on_the_line:
        lines.append(f"{_bare(task.text)} is still open, with a {days}-day streak on the line.")
    if not lines:
        return ""
    script.say(" ".join(lines))
    return " ".join(lines)


def _week(script: _Script, week: Week) -> str:
    """Sunday's look back: completion rate, each habit, wins, best streak, and what slipped."""
    days = min(week.days_tracked, 7)
    span = "this week" if days == 7 else f"over the {days} days I've been keeping track"
    spoken, written = ["Here's your week."], [f"This week ({_span(week)})"]
    if week.rate is not None:
        spoken.append(f"You checked off {week.done} of {week.planned} tasks {span}. That's {week.rate} percent.")
        written[0] += f": {week.done} of {week.planned} done ({week.rate}%)"
    for habit, count in week.habits.items():
        spoken.append(f"{_bare(habit)}: {count} of {days} days.")
        written.append(f"{habit}: {count}/{days} days")
    if week.wins:
        names = [_bare(win) for win in week.wins[:MAX_SPOKEN_TASKS]]
        extra = len(week.wins) - len(names)
        spoken.append("Wins: " + _join(names + ([f"{extra} more"] if extra else [])) + ".")
        written.append("Wins: " + ", ".join(week.wins))
    if week.best_streak:
        habit, run = week.best_streak
        spoken.append(f"Best streak going: {_bare(habit)}, {run} days.")
        written.append(f"Best streak: {habit}, {run} days")
    slipped = [(habit, count) for habit, count in week.habits.items() if days >= 3 and count < days / 2]
    if slipped:
        habit, count = min(slipped, key=lambda pair: pair[1])
        spoken.append(f"{_bare(habit)} slipped to {count} of {days} days. Pick one thing to fix for next week.")
    script.say(" ".join(spoken))
    return "\n".join(written)


def _span(week: Week) -> str:
    """"Oct 26 – Nov 1"."""
    return f"{week.start:%b} {week.start.day} – {week.end:%b} {week.end.day}"


def _week_verdict(week: Week) -> str:
    if week.rate is None:
        return "That's the week. Rest up."
    if week.rate >= 80:
        return "Strong week. Keep it rolling."
    if week.rate >= 50:
        return "Solid week, with room to tighten up."
    return "Rough week. Next week's a fresh start."


def _evening_review(script: _Script, phrase: Phrase) -> str:
    script.say(f"Quick {phrase.language} review. Remember this one?")
    script.say(phrase.phrase, foreign=True)
    script.say(f"It means: {phrase.meaning}")
    return f"{phrase.language} review: {phrase.phrase}\nIt means: {phrase.meaning}"


def build_phrase_help(phrase: Phrase) -> Briefing:
    """/phrase: the phrase word by word and slowly, then at normal speed, with the spelling written out."""
    script = _Script()
    words = _words(phrase.phrase)
    if len(words) > 1:
        script.say("Here it is, word by word.")
        for word in words:
            script.say(word, foreign=True, slow=True)
        script.say("All together, slowly:")
    else:
        script.say("Here it is, slowly:")
    script.say(phrase.phrase, foreign=True, slow=True)
    script.say("And at normal speed:")
    script.say(phrase.phrase, foreign=True)
    note = f" {phrase.note}" if phrase.note else ""
    text = f"{phrase.phrase}\nIt means: {phrase.meaning}{note}"
    if len(words) > 1:
        text += "\nWord by word: " + " · ".join(words)
    return Briefing(script.segments, text)


def _words(phrase: str) -> list[str]:
    """The phrase's words without punctuation, e.g. "¿Qué tal?" -> ["Qué", "tal"]."""
    return [word for word in (raw.strip("¿?¡!.,;:") for raw in phrase.split()) if word]


def _evening_closing(tasks: list[Task] | None) -> str:
    if not tasks:
        return "Enjoy your evening."
    done = sum(task.done for task in tasks)
    if done == len(tasks):
        return "Nice work today."
    if done:
        return "Good push today. Rest up."
    return "Tomorrow's a fresh start."


def _names(tasks: list[Task], limit: int = MAX_SPOKEN_TASKS) -> str:
    """Tasks as a spoken list, capped so a long list doesn't drag on."""
    names = [_bare(task.text) for task in tasks[:limit]]
    extra = len(tasks) - len(names)
    if extra:
        names.append(f"{extra} more")
    return _join(names)


def _bare(task: str) -> str:
    """A task as it reads mid-sentence, without its own end punctuation."""
    return task.rstrip(".!")


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _year(year: int) -> str:
    return f"{-year} BC" if year < 0 else str(year)
