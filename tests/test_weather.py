import httpx

from coach.sources.weather import Weather, fetch_weather

# Trimmed from a real Open-Meteo response for Tampa.
SAMPLE = {
    "current": {"time": "2026-10-28T19:15", "temperature_2m": 76.9},
    "daily": {
        "time": ["2026-10-28"],
        "temperature_2m_max": [83.0],
        "temperature_2m_min": [67.8],
        "precipitation_probability_max": [2],
        "weather_code": [3],
    },
}


def fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def fetch(handler, **kwargs):
    return fetch_weather(27.9506, -82.4572, "America/New_York", client=fake_client(handler), **kwargs)


def test_parses_open_meteo_response():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=SAMPLE)

    assert fetch(handler) == Weather(current_temp=77, high=83, low=68, rain_chance=2, summary="overcast")
    assert seen["temperature_unit"] == "fahrenheit"
    assert seen["timezone"] == "America/New_York"


def test_passes_celsius_through():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=SAMPLE)

    fetch(handler, temperature_unit="celsius")
    assert seen["temperature_unit"] == "celsius"


def test_unknown_code_and_missing_rain_chance():
    data = {**SAMPLE, "daily": {**SAMPLE["daily"], "weather_code": [42], "precipitation_probability_max": [None]}}
    weather = fetch(lambda request: httpx.Response(200, json=data))
    assert weather.summary == "mixed conditions"
    assert weather.rain_chance == 0


def test_tomorrow_uses_the_second_day():
    seen = {}
    data = {**SAMPLE, "daily": {
        "time": ["2026-10-28", "2026-10-29"],
        "temperature_2m_max": [83.0, 86.4],
        "temperature_2m_min": [67.8, 70.2],
        "precipitation_probability_max": [2, 40],
        "weather_code": [3, 61],
    }}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=data)

    assert fetch(handler, days_ahead=1) == Weather(current_temp=77, high=86, low=70, rain_chance=40,
                                                   summary="light rain")
    assert seen["forecast_days"] == "2"


def test_server_error_returns_none():
    assert fetch(lambda request: httpx.Response(500)) is None


def test_network_failure_returns_none():
    def handler(request):
        raise httpx.ConnectError("no internet")

    assert fetch(handler) is None


def test_unexpected_shape_returns_none():
    assert fetch(lambda request: httpx.Response(200, json={"daily": {}})) is None
    assert fetch(lambda request: httpx.Response(200, text="not json")) is None
