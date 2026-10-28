"""Data sources for the briefing: weather, tasks, daily content."""
import httpx

USER_AGENT = "CoachBot/0.1 (https://github.com/TyBM223/daily-voice-coach)"


def new_client() -> httpx.Client:
    """HTTP client for the free APIs: short timeout, and a User-Agent (Wikipedia requires one)."""
    return httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})
