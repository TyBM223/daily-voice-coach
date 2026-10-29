"""Builds what the coach says: the morning briefing and the evening wrap-up (each a spoken
script split into voice segments, plus a written copy), and the one-line midday check-in."""
from dataclasses import dataclass
from datetime import datetime

from coach.sources.content import ContentItem, Fact, HistoryMoment, Joke, Phrase, Quote
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
) -> Briefing:
    """Assemble the briefing. tasks is None when tasks.json couldn't be read; quote, when quotes.json couldn't."""
    script = _Script()
    written = [
        _greeting(script, name, now),
        _weather(script, weather, place),
        _tasks(script, tasks),
        _content(script, item),
        _closing(script, quote),
    ]
    return Briefing(script.segments, "\n\n".join(written))


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
    script.say(f"One for the road: {quote.text} That's {quote.author}.")
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
) -> Briefing:
    """The evening wrap-up: how today went, then a look at tomorrow. Short, about 20-30 seconds.
    tasks / tomorrow_tasks are None when tasks.json couldn't be read."""
    script = _Script()
    script.say(f"Evening, {name}.")
    written = [f"Evening, {name}.", _recap(script, tasks), _tomorrow(script, tomorrow_weather, tomorrow_tasks)]
    closing = _evening_closing(tasks)
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
