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

    for slot in ("morning", "midday", "evening"):
        hour, minute = map(int, config["schedule"][slot].split(":"))
        assert 0 <= hour < 24 and 0 <= minute < 60

    assert set(config["content_rotation"]) == WEEKDAYS
    assert set(config["content_rotation"].values()) <= CONTENT_TYPES
