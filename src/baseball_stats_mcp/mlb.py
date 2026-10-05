"""MLB data via the public MLB Stats API (statsapi.mlb.com).

No key is needed. MLB's copyright notice limits the data to personal,
non-commercial use, so keep this server for personal projects and demos.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .errors import DataError
from .lines import BattingLine, PitchingLine, combine, parse_ip
from .metrics import LeagueContext

BASE_URL = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "baseball-stats-mcp/0.1 (personal project)"
CACHE_TTL_SECONDS = 600
MLB_SPORT_ID = 1

DIVISIONS = {
    200: "AL West",
    201: "AL East",
    202: "AL Central",
    203: "NL West",
    204: "NL East",
    205: "NL Central",
}

_BATTING_MAP = {
    "G": "gamesPlayed", "PA": "plateAppearances", "AB": "atBats", "R": "runs", "H": "hits",
    "doubles": "doubles", "triples": "triples", "HR": "homeRuns", "RBI": "rbi",
    "SB": "stolenBases", "CS": "caughtStealing", "BB": "baseOnBalls", "IBB": "intentionalWalks",
    "HBP": "hitByPitch", "SO": "strikeOuts", "SF": "sacFlies", "SH": "sacBunts",
    "GDP": "groundIntoDoublePlay",
}
_PITCHING_MAP = {
    "G": "gamesPitched", "GS": "gamesStarted", "W": "wins", "L": "losses", "SV": "saves",
    "HLD": "holds", "BF": "battersFaced", "AB": "atBats", "H": "hits", "HR": "homeRuns",
    "BB": "baseOnBalls", "IBB": "intentionalWalks", "SO": "strikeOuts", "R": "runs",
    "ER": "earnedRuns", "SF": "sacFlies",
}


def _int(stat: dict[str, Any], key: str) -> int:
    value = stat.get(key)
    try:
        return int(value) if value not in (None, "", "-") else 0
    except (TypeError, ValueError):
        return 0


def batting_from_split(split: dict[str, Any]) -> BattingLine:
    stat = split.get("stat", {})
    return BattingLine(
        name=split.get("player", {}).get("fullName", ""),
        team=split.get("team", {}).get("name", ""),
        season=str(split.get("season", "")),
        player_id=str(split.get("player", {}).get("id", "")) or None,
        **{field: _int(stat, key) for field, key in _BATTING_MAP.items()},
    )


def pitching_from_split(split: dict[str, Any]) -> PitchingLine:
    stat = split.get("stat", {})
    outs = _int(stat, "outs") or parse_ip(stat.get("inningsPitched"))
    hbp = _int(stat, "hitBatsmen") or _int(stat, "hitByPitch")
    return PitchingLine(
        name=split.get("player", {}).get("fullName", ""),
        team=split.get("team", {}).get("name", ""),
        season=str(split.get("season", "")),
        player_id=str(split.get("player", {}).get("id", "")) or None,
        outs=outs,
        HBP=hbp,
        **{field: _int(stat, key) for field, key in _PITCHING_MAP.items()},
    )


def _line_from_split(split: dict[str, Any], group: str) -> BattingLine | PitchingLine:
    return batting_from_split(split) if group == "hitting" else pitching_from_split(split)


class MLBSource:
    league = "MLB"

    def __init__(self, client: httpx.AsyncClient | None = None, ttl: float = CACHE_TTL_SECONDS):
        self._client = client
        self._ttl = ttl
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT})
        try:
            resp = await self._client.get(f"{BASE_URL}{path}", params=params)
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise DataError("MLB Stats API timed out. Try again in a moment.") from e
        except httpx.HTTPStatusError as e:
            raise DataError(
                f"MLB Stats API returned HTTP {e.response.status_code} for {path}. "
                "Check the season/player id; the API may also be temporarily down."
            ) from e
        except httpx.RequestError as e:
            raise DataError(f"Could not reach the MLB Stats API ({type(e).__name__}). Check the network.") from e
        data = resp.json()
        self._cache[key] = (time.monotonic() + self._ttl, data)
        return data

    # ---- players -------------------------------------------------------

    async def search_players(self, name: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._get("/people/search", {"names": name, "sportIds": MLB_SPORT_ID})
        people = data.get("people", [])[:limit]
        return [
            {
                "id": p.get("id"),
                "name": p.get("fullName"),
                "position": p.get("primaryPosition", {}).get("abbreviation"),
                "bats": p.get("batSide", {}).get("code"),
                "throws": p.get("pitchHand", {}).get("code"),
                "active": p.get("active"),
                "mlb_debut": p.get("mlbDebutDate"),
            }
            for p in people
        ]

    async def resolve_player(self, player: str) -> tuple[str, str]:
        """Return (player_id, full_name) for a numeric id or an English name."""
        player = player.strip()
        if player.isdigit():
            data = await self._get(f"/people/{player}")
            people = data.get("people", [])
            if not people:
                raise DataError(f"No MLB player with id {player}.")
            return player, people[0].get("fullName", player)
        matches = await self.search_players(player, limit=25)
        if not matches:
            raise DataError(
                f"No MLB player matched '{player}'. Use the English name as MLB writes it "
                "(e.g. 'Ha-Seong Kim', 'Shohei Ohtani') or call mlb_search_players."
            )
        exact = [m for m in matches if (m["name"] or "").lower() == player.lower()]
        if len(exact) == 1:
            return str(exact[0]["id"]), exact[0]["name"]
        if len(matches) == 1:
            return str(matches[0]["id"]), matches[0]["name"]
        listing = "; ".join(f"{m['name']} (id {m['id']}, {m['position']}, debut {m['mlb_debut']})" for m in matches[:8])
        raise DataError(f"'{player}' matches several MLB players: {listing}. Call again with the numeric id.")

    async def player_line(
        self, player: str, season: int, group: str, team: str | None = None
    ) -> BattingLine | PitchingLine:
        player_id, full_name = await self.resolve_player(player)
        data = await self._get(
            f"/people/{player_id}/stats",
            {"stats": "season", "group": group, "season": season, "gameType": "R"},
        )
        splits = (data.get("stats") or [{}])[0].get("splits", [])
        if not splits:
            raise DataError(f"No {group} stats for {full_name} in the {season} MLB regular season.")
        # Traded players get one split per team; a split without a team is the season total.
        total = [s for s in splits if not s.get("team")]
        if total:
            line = _line_from_split(total[0], group)
            line.team = "/".join(s["team"]["name"] for s in splits if s.get("team"))
        else:
            lines = [_line_from_split(s, group) for s in splits]
            if team:
                lines = [l for l in lines if team.lower() in l.team.lower()] or lines
            line = combine(lines)
        line.name = line.name or full_name
        line.player_id = player_id
        line.season = str(season)
        return line

    async def season_lines(
        self, season: int, group: str, qualified: bool = True
    ) -> tuple[list[BattingLine | PitchingLine], str]:
        data = await self._get(
            "/stats",
            {
                "stats": "season",
                "group": group,
                "season": season,
                "sportId": MLB_SPORT_ID,
                "gameType": "R",
                "playerPool": "qualified" if qualified else "all",
                "limit": 2000,
            },
        )
        splits = (data.get("stats") or [{}])[0].get("splits", [])
        if not splits:
            raise DataError(f"MLB Stats API returned no {group} rows for {season}.")
        note = "MLB qualified players (official PA/IP thresholds)" if qualified else "All MLB players"
        return [_line_from_split(s, group) for s in splits], note

    async def league_context(self, season: int) -> LeagueContext:
        data = await self._get(
            "/teams/stats",
            {"stats": "season", "group": "pitching", "season": season, "sportIds": MLB_SPORT_ID, "gameType": "R"},
        )
        splits = (data.get("stats") or [{}])[0].get("splits", [])
        if not splits:
            raise DataError(f"No MLB team pitching totals for {season}.")
        totals = combine([pitching_from_split(s) for s in splits])
        return LeagueContext.from_totals(
            totals, league="MLB", season=str(season), source=f"Sum of {len(splits)} MLB team pitching lines"
        )

    # ---- standings -----------------------------------------------------

    async def standings(self, season: int) -> list[dict[str, Any]]:
        data = await self._get(
            "/standings", {"leagueId": "103,104", "season": season, "standingsTypes": "regularSeason"}
        )
        divisions = []
        for rec in data.get("records", []):
            div_id = rec.get("division", {}).get("id")
            teams = []
            for t in rec.get("teamRecords", []):
                teams.append(
                    {
                        "team": t.get("team", {}).get("name"),
                        "w": t.get("wins", 0),
                        "l": t.get("losses", 0),
                        "pct": t.get("winningPercentage"),
                        "gb": t.get("gamesBack"),
                        "rs": t.get("runsScored", 0),
                        "ra": t.get("runsAllowed", 0),
                        "diff": t.get("runDifferential", 0),
                        "streak": (t.get("streak") or {}).get("streakCode"),
                        "division_rank": t.get("divisionRank"),
                    }
                )
            divisions.append({"division": DIVISIONS.get(div_id, f"Division {div_id}"), "teams": teams})
        if not divisions:
            raise DataError(f"No MLB standings returned for {season}.")
        return divisions
