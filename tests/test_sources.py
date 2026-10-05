import httpx
import pytest
import respx

from baseball_stats_mcp.errors import DataError
from baseball_stats_mcp.kbo import KBOSource
from baseball_stats_mcp.mlb import MLBSource

from .conftest import MLB, OHTANI_2025_HITTING, PITCHER_STAT, stats_payload, split

# ---------------------------------------------------------------- MLB


@respx.mock
async def test_mlb_player_line_by_name():
    respx.get(f"{MLB}/people/search").respond(json={"people": [
        {"id": 660271, "fullName": "Shohei Ohtani", "primaryPosition": {"abbreviation": "TWP"}},
    ]})
    respx.get(f"{MLB}/people/660271/stats").respond(json=stats_payload([split(OHTANI_2025_HITTING, name="Shohei Ohtani", pid=660271)]))
    line = await MLBSource().player_line("Shohei Ohtani", 2025, "hitting")
    assert (line.name, line.HR, line.PA, line.player_id) == ("Shohei Ohtani", 55, 727, "660271")


@respx.mock
async def test_mlb_ambiguous_name_lists_candidates():
    respx.get(f"{MLB}/people/search").respond(json={"people": [
        {"id": 1, "fullName": "Will Smith", "primaryPosition": {"abbreviation": "C"}, "mlbDebutDate": "2019-05-28"},
        {"id": 2, "fullName": "Will Smith", "primaryPosition": {"abbreviation": "P"}, "mlbDebutDate": "2012-05-23"},
    ]})
    with pytest.raises(DataError, match="several MLB players"):
        await MLBSource().player_line("Will Smith", 2025, "hitting")


@respx.mock
async def test_mlb_traded_player_uses_total_split():
    respx.get(f"{MLB}/people/5/stats").respond(json=stats_payload([
        split(PITCHER_STAT, name="Traded Arm", pid=5, team=None),
        split({**PITCHER_STAT, "outs": 300}, name="Traded Arm", pid=5, team="Team A"),
        split({**PITCHER_STAT, "outs": 240}, name="Traded Arm", pid=5, team="Team B"),
    ]))
    respx.get(f"{MLB}/people/5").respond(json={"people": [{"id": 5, "fullName": "Traded Arm"}]})
    line = await MLBSource().player_line("5", 2025, "pitching")
    assert line.outs == 540 and line.team == "Team A/Team B"


@respx.mock
async def test_mlb_traded_player_sums_when_no_total_split():
    respx.get(f"{MLB}/people/5/stats").respond(json=stats_payload([
        split({**PITCHER_STAT, "outs": 300}, name="Traded Arm", pid=5, team="Team A"),
        split({**PITCHER_STAT, "outs": 240}, name="Traded Arm", pid=5, team="Team B"),
    ]))
    respx.get(f"{MLB}/people/5").respond(json={"people": [{"id": 5, "fullName": "Traded Arm"}]})
    line = await MLBSource().player_line("5", 2025, "pitching")
    assert line.outs == 540 and line.SO == 400


@respx.mock
async def test_mlb_http_error_becomes_data_error():
    respx.get(f"{MLB}/people/search").respond(status_code=503)
    with pytest.raises(DataError, match="HTTP 503"):
        await MLBSource().search_players("Kim")


@respx.mock
async def test_mlb_network_error_becomes_data_error():
    respx.get(f"{MLB}/people/search").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(DataError, match="Could not reach"):
        await MLBSource().search_players("Kim")


@respx.mock
async def test_mlb_responses_are_cached():
    route = respx.get(f"{MLB}/people/search").respond(json={"people": []})
    src = MLBSource()
    await src.search_players("Kim")
    await src.search_players("Kim")
    assert route.call_count == 1


# ---------------------------------------------------------------- KBO


async def test_kbo_reads_cp949_korean_headers(kbo_dir):
    src = KBOSource(kbo_dir)
    line = await src.player_line("가상타자", 2026, "hitting")
    assert (line.team, line.HR, line.SH, line.PA) == ("가상A", 25, 6, 600)


async def test_kbo_parses_fractional_innings(kbo_dir):
    line = await KBOSource(kbo_dir).player_line("가상에이스", 2026, "pitching")
    assert line.outs == 170 * 3 + 1
    assert line.AB == 0  # not in the CSV -> BABIP will be approximated


async def test_kbo_same_name_needs_team(kbo_dir):
    src = KBOSource(kbo_dir)
    with pytest.raises(DataError, match="several KBO players"):
        await src.player_line("동명이인", 2026, "hitting")
    line = await src.player_line("동명이인", 2026, "hitting", team="가상C")
    assert line.HR == 6


async def test_kbo_qualified_filter_uses_max_games(kbo_dir):
    lines, note = await KBOSource(kbo_dir).season_lines(2026, "hitting", qualified=True)
    assert [l.name for l in lines] == ["가상타자"]  # 600 PA >= 3.1 * 144
    assert "144" in note


async def test_kbo_missing_file_explains_what_to_do(kbo_dir):
    with pytest.raises(DataError, match="hitters_2025.csv"):
        await KBOSource(kbo_dir).player_line("가상타자", 2025, "hitting")


async def test_kbo_missing_required_column(kbo_dir):
    (kbo_dir / "hitters_2024.csv").write_text("선수명,팀명,AB,H\nA,B,10,3\n", encoding="utf-8")
    with pytest.raises(DataError, match="missing required columns"):
        KBOSource(kbo_dir).load(2024, "hitting")


async def test_kbo_fip_constant_override(kbo_dir):
    (kbo_dir / "league_overrides.json").write_text('{"2026": {"fip_constant": 4.5}}', encoding="utf-8")
    lg = await KBOSource(kbo_dir).league_context(2026)
    assert lg.fip_constant == 4.5
    assert "league_overrides.json" in lg.source


def test_kbo_status_lists_files(kbo_dir):
    status = KBOSource(kbo_dir).status()
    assert {f["file"] for f in status["files"]} == {"hitters_2026.csv", "pitchers_2026.csv"}
    assert all("error" not in f for f in status["files"])
