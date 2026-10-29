from datetime import time
from zoneinfo import ZoneInfo

from coach.main import load_config

WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
CONTENT_TYPES = {"phrase", "fact", "history", "joke", "phrase_review", "mix"}


def test_config_loads_with_required_settings():
    config = load_config()

    ZoneInfo(config["timezone"])  # raises if the zone is unknown (needs tzdata on Windows)
    assert -90 <= config["location"]["lat"] <= 90
    assert -180 <= config["location"]["lon"] <= 180
    assert config["temperature_unit"] in {"fahrenheit", "celsius"}
    assert config["voice"] and config["phrase_voice"]

    schedule = config["schedule"]
    for slot in ("morning_weekdays", "morning_weekends"):
        assert schedule[slot] == "wake" or time.fromisoformat(schedule[slot])
    assert time.fromisoformat(schedule["wake_earliest"]) < time.fromisoformat(schedule["wake_latest"])
    for slot in ("midday", "evening"):
        time.fromisoformat(schedule[slot])  # raises if it isn't a valid HH:MM time

    assert set(config["content_rotation"]) == WEEKDAYS
    assert set(config["content_rotation"].values()) <= CONTENT_TYPES
