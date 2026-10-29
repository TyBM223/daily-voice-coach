"""Ty's teams: games and headlines from ESPN's public site data (free, no key, no account).

It's unofficial, so ESPN can change it without notice. Anything that goes wrong just means
no sports today (logged); the rest of the briefing is unaffected. Teams are set in config.yaml:
  name: what the coach calls the team ("Heat")
  team: ESPN's team ID (the number in the team's espn.com URL)
  leagues: ESPN sport/league paths, e.g. [basketball/nba]; soccer clubs can list their cups too
  keywords: optional words that mark a headline as being about the team (default: [name])
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from coach.sources import new_client

log = logging.getLogger(__name__)

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NEWS_LIMIT = 50  # recent stories per league to search for the team's name
# Preferred broadcast types: national TV first, then a subscription package; foreign streams last.
TV_ORDER = ("TV", "Subscription Package")


@dataclass
class Game:
    team: str  # the team's name from config.yaml
    opponent: str
    home: bool
    start: datetime  # in the coach's time zone
    state: str  # "pre" (not started), "in" (on now) or "post" (final)
    tv: str | None = None
    score: tuple[int, int] | None = None  # (team, opponent) once the game has started
    sport: str = ""  # "football", "basketball", "soccer"
    won: bool | None = None  # ESPN's winner flag: settles a level score decided on penalties


@dataclass
class Headline:
    team: str
    title: str
    url: str | None
    published: datetime


def fetch_games(teams: list[dict], tz: ZoneInfo, client: httpx.Client | None = None) -> list[Game]:
    """This season's listed games for every team, oldest first. A team ESPN can't serve is skipped."""
    games = []
    with (client or new_client()) as http:
        for team in teams:
            for league in team["leagues"]:
                urls = [f"{ESPN}/{league}/teams/{team['team']}/schedule"]
                if league.startswith("soccer/"):
                    urls.append(urls[0] + "?fixture=true")  # soccer lists results and fixtures separately
                for url in urls:
                    try:
                        response = http.get(url)
                        response.raise_for_status()
                        games += _parse_schedule(response.json(), team, league, tz)
                    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, StopIteration) as e:
                        log.warning("ESPN schedule unavailable for %s (%s): %s", team["name"], league, e)
    unique = {(game.team, game.start, game.opponent): game for game in games}
    return sorted(unique.values(), key=lambda game: game.start)


def fetch_headlines(teams: list[dict], since: datetime, client: httpx.Client | None = None) -> list[Headline]:
    """Stories about the teams published since `since`, newest first, one entry per story."""
    found = {}
    with (client or new_client()) as http:
        for team in teams:
            league = team["leagues"][0]
            words = team.get("keywords") or [team["name"]]
            # Case-sensitive whole words, so "Heat" doesn't match "heat wave".
            pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in words) + r")\b")
            try:
                response = http.get(f"{ESPN}/{league}/news", params={"team": team["team"], "limit": NEWS_LIMIT})
                response.raise_for_status()
                for article in response.json().get("articles", []):
                    if article.get("type") == "Media":
                        continue  # video clips; stories and recaps read better
                    title = article["headline"].strip()
                    published = datetime.fromisoformat(article["published"])
                    if published < since or title in found:
                        continue
                    if pattern.search(title) or pattern.search(article.get("description") or ""):
                        url = article.get("links", {}).get("web", {}).get("href")
                        found[title] = Headline(team["name"], title, url, published)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
                log.warning("ESPN news unavailable for %s: %s", team["name"], e)
    return sorted(found.values(), key=lambda headline: headline.published, reverse=True)


def clock(moment: datetime) -> str:
    """A game time as it's said: "8 PM", "12:45 PM"."""
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00", "")


def matchup(game: Game, versus: str = "versus") -> str:
    """"Heat versus Pacers" at home, "Auburn at Ole Miss" away."""
    return f"{game.team} {versus if game.home else 'at'} {game.opponent}"


def result(game: Game) -> str:
    """"Heat beat Hawks, 129 to 117", "Heat lost to Hawks, 117 to 104", "Chelsea drew with Arsenal, 1 to 1",
    "Chelsea lost to Liverpool on penalties after a 1 to 1 draw"."""
    ours, theirs = game.score
    if ours > theirs:
        return f"{game.team} beat {game.opponent}, {ours} to {theirs}"
    if ours < theirs:
        return f"{game.team} lost to {game.opponent}, {theirs} to {ours}"
    if game.won is not None:
        verb = "beat" if game.won else "lost to"
        return f"{game.team} {verb} {game.opponent} on penalties after a {ours} to {theirs} draw"
    return f"{game.team} drew with {game.opponent}, {ours} to {theirs}"


def _parse_schedule(data: dict, team: dict, league: str, tz: ZoneInfo) -> list[Game]:
    team_id = str(data["team"]["id"])
    games = []
    for event in data.get("events", []):
        competition = event["competitions"][0]
        ours = next(c for c in competition["competitors"] if str(c["team"]["id"]) == team_id)
        theirs = next(c for c in competition["competitors"] if c is not ours)
        state = competition["status"]["type"]["state"]
        score = None
        if state != "pre" and "score" in ours and "score" in theirs:
            score = (_points(ours["score"]), _points(theirs["score"]))
        games.append(Game(
            team=team["name"],
            opponent=theirs["team"].get("shortDisplayName") or theirs["team"]["displayName"],
            home=ours["homeAway"] == "home",
            start=datetime.fromisoformat(event["date"]).astimezone(tz),
            state=state,
            tv=_tv(competition.get("broadcasts", [])),
            score=score,
            sport=league.split("/")[0],
            won=ours.get("winner") if state == "post" and (ours.get("winner") or theirs.get("winner")) else None,
        ))
    return games


def _points(score) -> int:
    """ESPN gives a score as a number, a string, or {"value": 2.0, "displayValue": "2"}."""
    return round(float(score["value"] if isinstance(score, dict) else score))


def _tv(broadcasts: list[dict]) -> str | None:
    def rank(broadcast):
        kind = broadcast.get("type", {}).get("shortName")
        return TV_ORDER.index(kind) if kind in TV_ORDER else len(TV_ORDER)
    names = [b for b in sorted(broadcasts, key=rank) if b.get("media", {}).get("shortName")]
    return names[0]["media"]["shortName"] if names else None
