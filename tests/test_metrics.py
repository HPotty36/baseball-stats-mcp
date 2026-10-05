import pytest

from baseball_stats_mcp.errors import DataError
from baseball_stats_mcp.formatting import fmt
from baseball_stats_mcp.lines import BattingLine, PitchingLine, combine, parse_ip
from baseball_stats_mcp.metrics import LeagueContext, batting_metrics, luck_check, pitching_metrics, pythagorean
from baseball_stats_mcp.mlb import batting_from_split, pitching_from_split

from .conftest import OHTANI_2025_HITTING, PITCHER_STAT, TEAM_PITCHING, split


def test_batting_metrics_match_official_mlb_rates():
    line = batting_from_split(split(OHTANI_2025_HITTING, name="Shohei Ohtani", pid=660271))
    m = batting_metrics(line)
    # The API's own published rates for the same line
    assert fmt("avg", m["avg"]) == ".282"
    assert fmt("obp", m["obp"]) == ".392"
    assert fmt("slg", m["slg"]) == ".622"
    assert fmt("babip", m["babip"]) == ".315"
    assert m["iso"] == pytest.approx(380 / 611 - 172 / 611)
    assert m["bb_pct"] == pytest.approx(109 / 727)
    assert m["k_pct"] == pytest.approx(187 / 727)
    assert m["small_sample"] is False


def test_batting_metrics_handle_zero_denominators():
    m = batting_metrics(BattingLine(name="nobody"))
    assert m["avg"] is None and m["ops"] is None and m["iso"] is None


@pytest.mark.parametrize(
    "raw, outs",
    [("144.1", 433), ("144 1/3", 433), ("144⅔", 434), ("2/3", 2), ("144", 432),
     ("144.33", 433), ("144.67", 434), ("-", 0), ("", 0), (180.0, 540), ("1,234.2", 3704)],
)
def test_parse_ip(raw, outs):
    assert parse_ip(raw) == outs


def test_parse_ip_rejects_garbage():
    with pytest.raises(DataError):
        parse_ip("abc")


def _league() -> LeagueContext:
    totals = pitching_from_split(split(TEAM_PITCHING, name="", pid=0))
    return LeagueContext.from_totals(totals, league="MLB", season="2025", source="test")


def test_league_context_and_fip():
    lg = _league()
    assert lg.era == pytest.approx(9 * 650 / 1458)
    assert lg.fip_constant == pytest.approx(9 * 650 / 1458 - 1220 / 1458)
    assert lg.babip == pytest.approx(1170 / 3960)
    assert lg.lob_pct == pytest.approx(1210 / 1658)

    p = pitching_from_split(split(PITCHER_STAT, name="Test Pitcher", pid=1))
    m = pitching_metrics(p, lg)
    assert m["era"] == pytest.approx(4.0)
    assert m["fip"] == pytest.approx(28 / 180 + lg.fip_constant)
    assert m["babip"] == pytest.approx(140 / 465)
    assert m["babip_is_approx"] is False
    assert m["lob_pct"] == pytest.approx(126 / 188)
    assert m["ip_display"] == "180.0"


def test_league_fip_equals_league_era():
    # By construction the league's own FIP equals its ERA.
    totals = pitching_from_split(split(TEAM_PITCHING, name="", pid=0))
    lg = _league()
    assert pitching_metrics(totals, lg)["fip"] == pytest.approx(lg.era)


def test_luck_check_flags_low_strand_rate():
    p = pitching_from_split(split(PITCHER_STAT, name="Test Pitcher", pid=1))
    r = luck_check(p, _league())
    assert any("LOB%" in s for s in r["signals"])
    assert not any(s.startswith("ERA is") for s in r["signals"])  # gap 0.67 < 0.75 threshold
    assert "positive regression" in r["verdict"]


def test_luck_check_small_sample_caveat():
    p = PitchingLine(name="Callup", outs=45, BF=70, AB=62, H=20, HR=4, BB=6, HBP=1, SO=12, R=14, ER=13)
    r = luck_check(p, _league())
    assert r["caveats"][0].startswith("Small sample")


def test_combine_sums_counting_stats_and_joins_teams():
    a = BattingLine(name="X", team="A", AB=100, H=30, HR=5)
    b = BattingLine(name="X", team="B", AB=50, H=10, HR=1)
    c = combine([a, b])
    assert (c.AB, c.H, c.HR, c.team) == (150, 40, 6, "A/B")


def test_pythagorean():
    pct, wins = pythagorean(800, 700, 162, exponent=2.0)
    assert pct == pytest.approx(640000 / 1130000)
    assert wins == pytest.approx(162 * 640000 / 1130000)


def test_standings_number_formats():
    assert fmt("pythag_w", 90.2) == "90.2"
    assert fmt("luck", 7.8) == "+7.8"
    assert fmt("luck", -12.6) == "-12.6"
