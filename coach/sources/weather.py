"""Today's weather from Open-Meteo (free, no API key)."""
import logging
from dataclasses import dataclass

import httpx

from coach.sources import new_client

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes (what Open-Meteo returns) as short spoken summaries.
WMO_SUMMARIES = {
    0: "clear skies",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}


@dataclass
class Weather:
    current_temp: int
    high: int
    low: int
    rain_chance: int  # percent, highest chance during the day
    summary: str  # the day's overall conditions, e.g. "partly cloudy"


def fetch_weather(
    lat: float,
    lon: float,
    timezone: str,
    temperature_unit: str = "fahrenheit",
    client: httpx.Client | None = None,
) -> Weather | None:
    """Return today's weather, or None if Open-Meteo can't be reached or answers oddly."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "temperature_unit": temperature_unit,
        "current": "temperature_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "forecast_days": 1,
    }
    try:
        with (client or new_client()) as http:
            response = http.get(FORECAST_URL, params=params)
            response.raise_for_status()
            data = response.json()
        daily = data["daily"]
        return Weather(
            current_temp=round(data["current"]["temperature_2m"]),
            high=round(daily["temperature_2m_max"][0]),
            low=round(daily["temperature_2m_min"][0]),
            rain_chance=round(daily["precipitation_probability_max"][0] or 0),
            summary=WMO_SUMMARIES.get(daily["weather_code"][0], "mixed conditions"),
        )
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        log.warning("Weather unavailable: %s", e)
        return None
