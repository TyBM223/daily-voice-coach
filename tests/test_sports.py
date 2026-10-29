from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from coach.sources.sports import Game, Headline, clock, fetch_games, fetch_headlines, matchup, result

TZ = ZoneInfo("America/New_York")
HEAT = {"name": "Heat", "team": "14", "leagues": ["basketball/nba"]}
CHELSEA = {"name": "Chelsea", "team": "363", "leagues": ["soccer/eng.1"]}


def competitor(team_id, name, home_away, score=None, winner=None):
    entry = {"homeAway": home_away, "team": {"id": team_id, "shortDisplayName": name, "displayName": name}}
    if score is not None:
        entry["score"] = score
    if winner is not None:
        entry["winner"] = winner
    return entry


def event(date, state, competitors, broadcasts=()):
    return {"date": date, "competitions": [{
        "status": {"type": {"state": state}},
        "competitors": competitors,
        "broadcasts": list(broadcasts),
    }]}


# Trimmed from real ESPN responses.
HEAT_SCHEDULE = {"team": {"id": "14"}, "events": [
    event("2026-10-28T23:00Z", "post", [
        competitor("1", "Hawks", "home", {"value": 117.0, "displayValue": "117"}, False),
        competitor("14", "Heat", "away", {"value": 129.0, "displayValue": "129"}, True),
    ], [{"type": {"shortName": "Subscription Package"}, "media": {"shortName": "NBA League Pass"}}]),
    event("2026-10-31T00:00Z", "pre", [
        competitor("14", "Heat", "home"),
        competitor("11", "Pacers", "away"),
    ], [{"type": {"shortName": "Streaming"}, "media": {"shortName": "DAZN IND"}},
        {"type": {"shortName": "Subscription Package"}, "media": {"shortName": "NBA League Pass"}}]),
]}
CHELSEA_RESULTS = {"team": {"id": "363"}, "events": [
    event("2026-10-28T20:00Z", "post", [
        competitor("364", "Liverpool", "home", {"value": 1.0}, True),
        competitor("363", "Chelsea", "away", {"value": 1.0}, False),
    ]),
]}
CHELSEA_FIXTURES = {"team": {"id": "363"}, "events": [
    event("2026-10-31T12:30Z", "pre", [
        competitor("363", "Chelsea", "home"),
        competitor("360", "Man Utd", "away"),
    ], [{"type": {"shortName": "TV"}, "media": {"shortName": "USA Net"}}]),
]}


def espn(routes):
    """A fake ESPN: routes maps a URL path (plus "?fixture=true" when asked) to its JSON."""
    def handler(request):
        key = request.url.path + ("?fixture=true" if request.url.params.get("fixture") else "")
        if key not in routes:
            return httpx.Response(404)
        return httpx.Response(200, json=routes[key])
    return httpx.Client(transport=httpx.MockTransport(handler))


NBA_PATH = "/apis/site/v2/sports/basketball/nba/teams/14/schedule"
EPL_PATH = "/apis/site/v2/sports/soccer/eng.1/teams/363/schedule"


def test_games_parse_time_side_tv_and_score():
    games = fetch_games([HEAT], TZ, client=espn({NBA_PATH: HEAT_SCHEDULE}))
    assert games == [
        Game("Heat", "Hawks", False, datetime(2026, 10, 28, 19, 0, tzinfo=TZ), "post", "NBA League Pass",
             (129, 117), "basketball", won=True),
        Game("Heat", "Pacers", True, datetime(2026, 10, 30, 20, 0, tzinfo=TZ), "pre", "NBA League Pass",
             None, "basketball"),
    ]


def test_soccer_asks_for_results_and_fixtures():
    client = espn({EPL_PATH: CHELSEA_RESULTS, EPL_PATH + "?fixture=true": CHELSEA_FIXTURES})
    games = fetch_games([CHELSEA], TZ, client=client)
    assert [(game.opponent, game.state, game.tv) for game in games] == [
        ("Liverpool", "post", None), ("Man Utd", "pre", "USA Net")]
    assert result(games[0]) == "Chelsea lost to Liverpool on penalties after a 1 to 1 draw"


def test_a_team_espn_cant_serve_is_skipped():
    games = fetch_games([CHELSEA, HEAT], TZ, client=espn({NBA_PATH: HEAT_SCHEDULE}))
    assert {game.team for game in games} == {"Heat"}


def test_espn_down_means_no_games():
    def offline(request):
        raise httpx.ConnectError("offline")
    assert fetch_games([HEAT], TZ, client=httpx.Client(transport=httpx.MockTransport(offline))) == []


def test_wording_helpers():
    pacers = Game("Heat", "Pacers", True, datetime(2026, 10, 30, 20, 0, tzinfo=TZ), "pre")
    ole_miss = Game("Auburn", "Ole Miss", False, datetime(2026, 10, 31, 12, 45, tzinfo=TZ), "pre")
    assert (matchup(pacers), matchup(ole_miss)) == ("Heat versus Pacers", "Auburn at Ole Miss")
    assert (clock(pacers.start), clock(ole_miss.start)) == ("8 PM", "12:45 PM")
    assert result(Game("Heat", "Hawks", False, pacers.start, "post", score=(104, 117))) == (
        "Heat lost to Hawks, 117 to 104")
    assert result(Game("Chelsea", "Arsenal", True, pacers.start, "post", score=(1, 1))) == (
        "Chelsea drew with Arsenal, 1 to 1")


# --- headlines --------------------------------------------------------------

def news(articles):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"articles": articles})))


def article(headline, published, description="", kind="Story", url="https://espn.com/story"):
    return {"headline": headline, "published": published, "description": description, "type": kind,
            "links": {"web": {"href": url}}}


SINCE = datetime(2026, 10, 28, 0, 0, tzinfo=TZ)


def test_headlines_about_the_team_since_yesterday_newest_first():
    client = news([
        article("Heat beat the Hawks for first win", "2026-10-29T02:34:00Z"),
        article("Giannis leads the way", "2026-10-29T11:12:00Z", description="Big night for the Heat."),
        article("Knicks roll past the Celtics", "2026-10-29T12:00:00Z"),  # not about the Heat
        article("Heat wave hits Phoenix", "2026-10-29T12:00:00Z"),  # known false positive: capital "Heat"
        article("Miami Heat vs. Atlanta Hawks: Game Highlights", "2026-10-29T01:53:00Z", kind="Media"),
        article("Heat preseason notes", "2026-10-20T12:00:00Z"),  # too old
    ])
    titles = [h.title for h in fetch_headlines([HEAT], SINCE, client=client)]
    assert titles == ["Heat wave hits Phoenix", "Giannis leads the way", "Heat beat the Hawks for first win"]


def test_heat_in_lowercase_doesnt_count():
    client = news([article("Scorching heat for the Bengals in Week 9", "2026-10-29T12:00:00Z")])
    assert fetch_headlines([HEAT], SINCE, client=client) == []


def test_keywords_from_config():
    niners = {"name": "49ers", "team": "25", "leagues": ["football/nfl"], "keywords": ["49ers", "Niners"]}
    client = news([article("Niners activate their star tight end", "2026-10-29T12:00:00Z", url="https://x")])
    assert fetch_headlines([niners], SINCE, client=client) == [
        Headline("49ers", "Niners activate their star tight end", "https://x",
                 datetime(2026, 10, 29, 12, 0, tzinfo=ZoneInfo("UTC")))]


def test_news_outage_means_no_headlines():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert fetch_headlines([HEAT], SINCE, client=client) == []
