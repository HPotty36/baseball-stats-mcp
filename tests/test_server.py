"""End-to-end: talk to the real MCP server in-process, the way Claude would."""

import json

import respx
from mcp import Client

from baseball_stats_mcp import server

from .conftest import MLB, PITCHER_STAT, TEAM_PITCHING, stats_payload, split

EXPECTED_TOOLS = {
    "baseball_player_stats",
    "baseball_leaderboard",
    "baseball_pitcher_luck_check",
    "mlb_search_players",
    "mlb_standings",
    "kbo_data_status",
}


def _text(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "text", None))


async def test_lists_all_tools_with_read_only_annotations(sources):
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    stats = next(t for t in tools if t.name == "baseball_player_stats")
    assert stats.input_schema["properties"]["league"]["enum"] == ["MLB", "KBO"]


async def test_kbo_player_stats_markdown(sources):
    async with Client(server.mcp) as client:
        r = await client.call_tool("baseball_player_stats", {"player": "가상타자", "league": "KBO"})
    assert not r.is_error, _text(r)
    text = _text(r)
    assert "가상타자" in text and "KBO 2026 hitting" in text and "| OPS |" in text


async def test_kbo_leaderboard_by_fip(sources):
    async with Client(server.mcp) as client:
        r = await client.call_tool(
            "baseball_leaderboard",
            {"league": "KBO", "group": "pitching", "sort_by": "fip", "qualified": False, "format": "json"},
        )
    assert not r.is_error, _text(r)
    data = json.loads(_text(r))
    fips = [row["fip"] for row in data["rows"]]
    assert fips == sorted(fips) and len(fips) == 3


async def test_bad_sort_key_is_a_readable_tool_error(sources):
    async with Client(server.mcp) as client:
        r = await client.call_tool("baseball_leaderboard", {"league": "KBO", "group": "hitting", "sort_by": "fip"})
    assert r.is_error and "not valid for hitting" in _text(r)


async def test_kbo_luck_check(sources):
    async with Client(server.mcp) as client:
        r = await client.call_tool("baseball_pitcher_luck_check", {"player": "불운투수", "league": "KBO"})
    assert not r.is_error, _text(r)
    text = _text(r)
    assert "Verdict" in text and "approximated" in text  # no AB column -> BABIP approximation caveat


@respx.mock
async def test_mlb_luck_check_end_to_end(sources):
    respx.get(f"{MLB}/people/search").respond(json={"people": [{"id": 1, "fullName": "Test Pitcher"}]})
    respx.get(f"{MLB}/people/1/stats").respond(json=stats_payload([split(PITCHER_STAT, name="Test Pitcher", pid=1, team="Atlanta Braves")]))
    respx.get(f"{MLB}/teams/stats").respond(json=stats_payload([split(TEAM_PITCHING, name="", pid=0)]))
    async with Client(server.mcp) as client:
        r = await client.call_tool(
            "baseball_pitcher_luck_check", {"player": "Test Pitcher", "season": 2025, "format": "json"}
        )
    assert not r.is_error, _text(r)
    data = json.loads(_text(r))
    assert data["team"] == "Atlanta Braves"
    assert data["metrics"]["era"] == 4.0
    assert "positive regression" in data["verdict"]


@respx.mock
async def test_mlb_standings_adds_pythagorean(sources):
    respx.get(f"{MLB}/standings").respond(json={"records": [{
        "division": {"id": 204},
        "teamRecords": [{"team": {"name": "Braves"}, "wins": 90, "losses": 72, "winningPercentage": ".556",
                          "gamesBack": "-", "runsScored": 800, "runsAllowed": 700, "runDifferential": 100,
                          "streak": {"streakCode": "W2"}, "divisionRank": "1"}],
    }]})
    async with Client(server.mcp) as client:
        r = await client.call_tool("mlb_standings", {"season": 2025, "format": "json"})
    team = json.loads(_text(r))["divisions"][0]["teams"][0]
    assert json.loads(_text(r))["divisions"][0]["division"] == "NL East"
    assert 90 < team["pythag_w"] < 92 and team["luck"] < 0  # 800 RS / 700 RA ~ 90.8 W


@respx.mock
async def test_mlb_outage_is_reported_not_crashed(sources):
    respx.get(f"{MLB}/people/search").respond(status_code=500)
    async with Client(server.mcp) as client:
        r = await client.call_tool("mlb_search_players", {"name": "Kim"})
    assert r.is_error and "HTTP 500" in _text(r)


async def test_kbo_data_status(sources):
    async with Client(server.mcp) as client:
        r = await client.call_tool("kbo_data_status", {})
    data = json.loads(_text(r))
    assert data["data_dir_exists"] and len(data["files"]) == 2


def test_default_mlb_season():
    import datetime as dt

    assert server.default_mlb_season(dt.date(2026, 10, 5)) == 2026
    assert server.default_mlb_season(dt.date(2027, 1, 15)) == 2026
