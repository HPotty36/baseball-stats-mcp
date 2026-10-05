"""Shared fixtures. All data here is synthetic except the MLB batting line, which
mirrors a real 2025 MLB Stats API response (Shohei Ohtani) for regression checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from baseball_stats_mcp import server
from baseball_stats_mcp.kbo import KBOSource
from baseball_stats_mcp.mlb import MLBSource

MLB = "https://statsapi.mlb.com/api/v1"

OHTANI_2025_HITTING = {
    "gamesPlayed": 158, "plateAppearances": 727, "atBats": 611, "runs": 146, "hits": 172,
    "doubles": 25, "triples": 9, "homeRuns": 55, "rbi": 102, "stolenBases": 20,
    "caughtStealing": 6, "baseOnBalls": 109, "intentionalWalks": 20, "hitByPitch": 3,
    "strikeOuts": 187, "sacFlies": 2, "sacBunts": 0, "groundIntoDoublePlay": 9,
    "avg": ".282", "obp": ".392", "slg": ".622", "ops": "1.014", "babip": ".315",
}

# Synthetic pitcher and league totals (round numbers so expected values are easy to check).
PITCHER_STAT = {
    "gamesPitched": 30, "gamesStarted": 30, "wins": 10, "losses": 8, "saves": 0, "holds": 0,
    "outs": 540, "inningsPitched": "180.0", "battersFaced": 750, "atBats": 680, "hits": 160,
    "homeRuns": 20, "baseOnBalls": 50, "intentionalWalks": 2, "hitBatsmen": 6, "hitByPitch": 6,
    "strikeOuts": 200, "runs": 90, "earnedRuns": 80, "sacFlies": 5,
}
TEAM_PITCHING = {
    "outs": 4374, "inningsPitched": "1458.0", "battersFaced": 6200, "atBats": 5500, "hits": 1350,
    "homeRuns": 180, "baseOnBalls": 500, "intentionalWalks": 20, "hitBatsmen": 60,
    "strikeOuts": 1400, "runs": 700, "earnedRuns": 650, "sacFlies": 40,
}

HITTERS_CSV = """선수명,팀명,G,PA,AB,R,H,2B,3B,HR,RBI,SB,CS,BB,IBB,HBP,SO,SF,SAC,GDP
가상타자,가상A,144,600,520,80,160,30,2,25,90,10,3,60,4,8,100,6,6,12
가상신인,가상B,60,180,160,20,40,8,0,3,15,2,1,15,0,2,50,1,2,3
동명이인,가상A,100,350,310,40,85,15,1,8,40,5,2,30,1,4,70,3,3,6
동명이인,가상C,90,300,270,35,70,12,0,6,30,3,1,25,0,2,60,2,1,5
"""

PITCHERS_CSV = """선수명,팀명,G,GS,W,L,SV,HLD,IP,TBF,H,HR,BB,IBB,HBP,SO,R,ER
가상에이스,가상A,28,28,12,6,0,0,170 1/3,700,150,15,45,1,5,180,60,55
불운투수,가상B,25,25,5,12,0,0,150,660,170,10,40,0,4,150,95,90
불펜투수,가상C,60,0,3,2,20,5,62 2/3,260,50,5,25,2,2,70,20,18
"""


@pytest.fixture
def kbo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "kbo"
    d.mkdir()
    # cp949, as Excel on Korean Windows would save it
    (d / "hitters_2026.csv").write_bytes(HITTERS_CSV.encode("cp949"))
    (d / "pitchers_2026.csv").write_text(PITCHERS_CSV, encoding="utf-8-sig")
    return d


@pytest.fixture
def sources(kbo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    srcs = {"MLB": MLBSource(), "KBO": KBOSource(kbo_dir)}
    monkeypatch.setattr(server, "SOURCES", srcs)
    return srcs


def stats_payload(splits: list[dict]) -> dict:
    return {"stats": [{"splits": splits}]}


def split(stat: dict, *, name: str, pid: int, team: str | None = "Los Angeles Dodgers", season: str = "2025") -> dict:
    s = {"season": season, "stat": stat, "player": {"id": pid, "fullName": name}}
    if team:
        s["team"] = {"id": 1, "name": team}
    return s
