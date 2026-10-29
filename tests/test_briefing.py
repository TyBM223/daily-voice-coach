from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from coach.briefing import build_briefing, build_evening, build_midday
from coach.sources.content import Fact, HistoryMoment, Joke, Phrase, Quote
from coach.sources.tasks import Task
from coach.sources.weather import Weather

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=ZoneInfo("America/New_York"))
WEATHER = Weather(current_temp=78, high=83, low=68, rain_chance=2, summary="overcast")
FACT = Fact("Octopuses have three hearts and blue blood.")
PHRASE = Phrase("Spanish", "¿Qué me recomiendas?", "What do you recommend?", "Great at restaurants.")
QUOTE = Quote("Make each day your masterpiece.", "John Wooden")


def build(weather=WEATHER, tasks=("Gym",), item=FACT, now=NOW, quote=QUOTE):
    """tasks may mix plain strings (one-off tasks) and Task objects."""
    if tasks is not None:
        tasks = [task if isinstance(task, Task) else Task(task) for task in tasks]
    return build_briefing("Ty", "Tampa", now, weather, tasks, item, quote)


def spoken(briefing):
    return " ".join(segment.text for segment in briefing.segments)


def test_greeting_has_name_date_and_time():
    briefing = build()
    assert spoken(briefing).startswith("Morning, Ty. It's Thursday, October 29, 8:00 AM.")
    assert briefing.text.startswith("Morning, Ty. Thursday, October 29, 8:00 AM.")


def test_weather_spoken_and_written():
    briefing = build()
    assert "Weather in Tampa: overcast, 78 degrees right now. High of 83, low of 68." in spoken(briefing)
    assert "Weather: Overcast, 78° now. High 83°, low 68°. 2% chance of rain." in briefing.text


@pytest.mark.parametrize("chance, expected", [
    (0, "Rain's not a factor today."),
    (30, "Rain chance is 30 percent."),
    (55, "keep an umbrella handy"),
    (90, "Bring an umbrella."),
])
def test_rain_wording(chance, expected):
    weather = Weather(current_temp=78, high=83, low=68, rain_chance=chance, summary="showers")
    assert expected in spoken(build(weather=weather))


def test_missing_weather():
    briefing = build(weather=None)
    assert "couldn't get the weather" in spoken(briefing)
    assert "Weather: unavailable" in briefing.text


def test_task_counts():
    assert "Nothing on your list today." in spoken(build(tasks=[]))
    assert "One thing on your list today: Gym." in spoken(build(tasks=["Gym"]))
    assert "You've got 2 things on your list: Gym and Call mom." in spoken(build(tasks=["Gym", "Call mom."]))


def test_long_task_list_is_trimmed_when_spoken_but_not_written():
    tasks = [f"Task {n}" for n in range(1, 8)]
    briefing = build(tasks=tasks)
    assert "You've got 7 things on your list: Task 1, Task 2, Task 3, Task 4, Task 5, and 2 more." in spoken(briefing)
    assert all(f"- {task}" in briefing.text for task in tasks)


def test_top_priority_is_the_first_one_off_task():
    tasks = [Task("Gym", daily=True), "Finish cover letter", "Call mom"]
    briefing = build(tasks=tasks)
    assert "Top priority: Finish cover letter. Knock that out first." in spoken(briefing)
    assert "- Call mom\nTop priority: Finish cover letter\n" in briefing.text


def test_no_priority_line_when_everything_is_daily_or_theres_one_task():
    assert "Top priority" not in spoken(build(tasks=[Task("Gym", daily=True), Task("Read", daily=True)]))
    assert "Top priority" not in spoken(build(tasks=["Finish cover letter"]))


def test_unreadable_tasks_file():
    briefing = build(tasks=None)
    assert "couldn't read your task file" in spoken(briefing)
    assert "Check it for a typo" in briefing.text


def test_new_phrase_is_spoken_twice_in_the_phrase_voice_then_slowly():
    briefing = build(item=PHRASE)
    foreign = [(segment.text, segment.slow) for segment in briefing.segments if segment.foreign]
    assert foreign == [("¿Qué me recomiendas?", False), ("¿Qué me recomiendas?", True)]
    assert "One more time, slowly:" in spoken(briefing)
    assert not any(segment.slow for segment in briefing.segments if not segment.foreign)
    assert all("¿Qué" not in segment.text for segment in briefing.segments if not segment.foreign)
    assert "It means: What do you recommend? Great at restaurants." in briefing.text


def test_phrase_review_is_spoken_once():
    review = Phrase("Spanish", "¿Qué me recomiendas?", "What do you recommend?", review=True)
    briefing = build(item=review)
    assert [segment.text for segment in briefing.segments if segment.foreign] == ["¿Qué me recomiendas?"]
    assert "Spanish review: ¿Qué me recomiendas?" in briefing.text


def test_history_wording():
    assert "On this day in 1965: The Gateway Arch was completed." in spoken(
        build(item=HistoryMoment("The Gateway Arch was completed.", year=1965)))
    assert "On this day in 44 BC:" in spoken(build(item=HistoryMoment("Something happened.", year=-44)))
    assert "A bit of history: In 1969, Apollo 11 landed on the Moon." in spoken(
        build(item=HistoryMoment("In 1969, Apollo 11 landed on the Moon.")))


def test_two_part_joke_gets_a_beat_before_the_punchline():
    briefing = build(item=Joke("Why do programmers prefer dark mode?", "Because light attracts bugs."))
    assert briefing.segments[0].text.endswith("Joke of the day: Why do programmers prefer dark mode?")
    assert briefing.segments[1].text.startswith("Because light attracts bugs.")


def test_one_liner_joke():
    assert "Joke of the day: I don't know y." in spoken(build(item=Joke("I don't know y.")))


def test_english_lines_are_merged_into_one_segment():
    assert len(build().segments) == 1


def test_ends_on_the_quote():
    briefing = build()
    assert spoken(briefing).endswith("One for the road: Make each day your masterpiece. That's John Wooden.")
    assert briefing.text.endswith('One for the road: "Make each day your masterpiece." — John Wooden')


def test_unreadable_quotes_fall_back_to_a_sign_off():
    briefing = build(quote=None)
    assert spoken(briefing).endswith("That's the rundown. Go get it.")
    assert briefing.text.endswith("That's the rundown. Go get it.")


def test_busiest_day_stays_under_75_seconds():
    # About 130 spoken words a minute, so 75 seconds is roughly 165 words.
    long_history = HistoryMoment(" ".join(["word"] * 45) + ".", year=1919)
    tasks = [f"Send applications to company number {n}" for n in range(1, 8)]
    longest_quote = Quote(" ".join(["word"] * 22) + ".", "Martin Luther King Jr.")  # the cap in test_content
    words = len(spoken(build(tasks=tasks, item=long_history, quote=longest_quote)).split())
    assert words <= 165


# --- midday -----------------------------------------------------------------

GYM_DONE = Task("Gym", daily=True, done=True)
APPS = Task("Send two job applications", daily=True)
LETTER = Task("Finish cover letter")


def test_midday_counts_whats_left():
    assert build_midday([GYM_DONE, APPS, LETTER]) == (
        "Midday check: 1 done, 2 to go: Send two job applications and Finish cover letter.")


def test_midday_with_nothing_checked_off_yet():
    assert build_midday([APPS, LETTER]).startswith("Midday check: nothing checked off yet. Still to do:")


def test_midday_when_everything_is_done():
    assert "everything's checked off" in build_midday([GYM_DONE])


def test_no_midday_without_tasks():
    assert build_midday([]) is None


# --- evening ----------------------------------------------------------------

TOMORROW = Weather(current_temp=75, high=86, low=70, rain_chance=40, summary="light rain")


def evening(tasks=(GYM_DONE, APPS, LETTER), weather=TOMORROW, upcoming=(APPS, Task("Call mom"))):
    return build_evening("Ty", None if tasks is None else list(tasks), weather,
                         None if upcoming is None else list(upcoming))


def test_evening_recaps_the_day_and_previews_tomorrow():
    briefing = evening()
    assert spoken(briefing) == (
        "Evening, Ty. You got 1 of 3 done today: Gym. "
        "Still open: Send two job applications and Finish cover letter. "
        "If you finished any of those, tap them off. Anything else can move to tomorrow. "
        "Tomorrow: light rain, high of 86, low of 70. Rain chance is 40 percent, so keep an umbrella handy. "
        "First up: Call mom. Good push today. Rest up."
    )
    assert briefing.text == (
        "Evening, Ty.\n\n"
        "Today: 1 of 3 done\n✅ Gym\n⬜ Send two job applications\n⬜ Finish cover letter\n\n"
        "Tomorrow: Light rain, high 86°, low 70°. 40% chance of rain.\nFirst up: Call mom\n\n"
        "Good push today. Rest up."
    )


def test_evening_clean_sweep():
    briefing = evening(tasks=[GYM_DONE, Task("Finish cover letter", done=True)])
    assert "You got everything done today: Gym and Finish cover letter. Clean sweep." in spoken(briefing)
    assert "tap them off" not in spoken(briefing)
    assert spoken(briefing).endswith("Nice work today.")


def test_evening_honest_when_nothing_got_done():
    briefing = evening(tasks=[APPS, LETTER])
    assert "Nothing checked off today. Still open:" in spoken(briefing)
    assert spoken(briefing).endswith("Tomorrow's a fresh start.")


def test_evening_only_daily_tasks_left_doesnt_mention_moving():
    assert "move to tomorrow" not in spoken(evening(tasks=[GYM_DONE, APPS]))


def test_evening_without_tasks_forecast_or_task_file():
    briefing = evening(tasks=None, weather=None, upcoming=None)
    assert "couldn't read your task file" in spoken(briefing)
    assert "couldn't get tomorrow's forecast" in spoken(briefing)
    assert "First up" not in spoken(briefing)
    assert spoken(evening(tasks=[])).endswith("Enjoy your evening.")


def test_evening_stays_short():
    # About 35 seconds at most (~130 words a minute), even with a long list of long task names.
    tasks = [Task(f"Send applications to company number {n}") for n in range(1, 9)]
    assert len(spoken(evening(tasks=tasks, upcoming=tasks)).split()) <= 80
