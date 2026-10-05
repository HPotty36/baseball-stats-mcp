"""MCP server exposing MLB + KBO stats with sabermetric metrics.

Run with:  uv run baseball-stats-mcp   (stdio transport, for Claude Desktop / Claude Code)
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import formatting as F
from .errors import DataError
from .kbo import KBOSource
from .lines import BattingLine, PitchingLine
from .metrics import (
    BATTING_ASCENDING,
    BATTING_SORT_KEYS,
    PITCHING_ASCENDING,
    PITCHING_SORT_KEYS,
    LeagueContext,
    batting_metrics,
    luck_check,
    pitching_metrics,
    pythagorean,
)
from .mlb import MLBSource

# httpx logs every request at INFO, which floods the MCP client's server log.
logging.getLogger("httpx").setLevel(logging.WARNING)

League = Literal["MLB", "KBO"]
Group = Literal["hitting", "pitching"]
Format = Literal["markdown", "json"]


class StatsSource(Protocol):
    league: str

    async def player_line(self, player: str, season: int, group: str, team: str | None = None) -> BattingLine | PitchingLine: ...
    async def season_lines(self, season: int, group: str, qualified: bool = True) -> tuple[list[Any], str]: ...
    async def league_context(self, season: int) -> LeagueContext: ...


def _default_kbo_dir() -> Path:
    env = os.environ.get("KBO_DATA_DIR")
    if env:
        return Path(env).expanduser()
    project_dir = Path(__file__).resolve().parents[2] / "data" / "kbo"
    return project_dir if project_dir.is_dir() else Path.cwd() / "data" / "kbo"


# Module-level so tests can swap them out.
SOURCES: dict[str, Any] = {"MLB": MLBSource(), "KBO": KBOSource(_default_kbo_dir())}

INSTRUCTIONS = """\
Baseball stats for MLB (live, official MLB Stats API) and KBO (local CSV files).
- MLB player names must be in English as MLB writes them (e.g. 'Ha-Seong Kim'); use mlb_search_players if unsure, then pass the numeric id.
- KBO player names are Korean, exactly as in the CSV. Call kbo_data_status first if a KBO call fails.
- Derived metrics (ISO, BABIP, BB%, K%, FIP, LOB%) are computed by this server from counting stats.
- Flag small samples and data dates when you report numbers; this server does not provide Statcast or WAR.
"""

mcp = MCPServer(name="baseball_stats_mcp", instructions=INSTRUCTIONS)

READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def default_mlb_season(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return today.year if today.month >= 3 else today.year - 1


def _source(league: str) -> Any:
    return SOURCES[league]


def _season(league: str, season: int | None, group: str) -> int:
    if season:
        return season
    if league == "KBO":
        return SOURCES["KBO"].latest_season(group)
    return default_mlb_season()


async def _context_or_none(src: Any, season: int) -> tuple[LeagueContext | None, str | None]:
    try:
        return await src.league_context(season), None
    except DataError as e:
        return None, f"FIP unavailable: {e}"


def _tool_error(e: DataError) -> ToolError:
    return ToolError(str(e))


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


@mcp.tool(name="baseball_player_stats", title="Player season stats", annotations=READ_ONLY_REMOTE)
async def baseball_player_stats(
    player: Annotated[str, Field(description="MLB: English name or numeric MLB id. KBO: Korean name as in the CSV.", min_length=1)],
    league: Annotated[League, Field(description="Which league's data to use.")] = "MLB",
    season: Annotated[int | None, Field(description="Season year. Default: current MLB season / latest KBO file.", ge=1876, le=2100)] = None,
    group: Annotated[Group, Field(description="'hitting' or 'pitching'.")] = "hitting",
    team: Annotated[str | None, Field(description="Optional team filter to disambiguate same-name players.")] = None,
    format: Annotated[Format, Field(description="'markdown' (default) or 'json'.")] = "markdown",
) -> str:
    """Get one player's regular-season line plus computed sabermetric rates.

    Hitting returns AVG/OBP/SLG/OPS, ISO, BABIP, BB%, K%, BB/K. Pitching returns ERA, FIP,
    ERA-FIP, WHIP, K%, BB%, K-BB%, BABIP, LOB%, HR/9 (FIP uses a league constant computed
    from that season's league totals). Use baseball_pitcher_luck_check for an ERA-vs-FIP read.
    """
    try:
        season_ = _season(league, season, group)
        src = _source(league)
        line = await src.player_line(player, season_, group, team)
        note = None
        lg = None
        if group == "hitting":
            m = batting_metrics(line)
            columns = F.BATTING_COLUMNS
        else:
            lg, note = await _context_or_none(src, season_)
            m = pitching_metrics(line, lg)
            columns = F.PITCHING_COLUMNS
    except DataError as e:
        raise _tool_error(e) from e

    if format == "json":
        return F.to_json({"league": league, "season": season_, "player": line.name, "team": line.team,
                          "player_id": line.player_id, "metrics": m,
                          "league_context": lg.as_dict() if lg else None, "note": note})
    parts = [f"**{line.name}** ({line.team or 'team n/a'}) - {league} {season_} {group}", "", F.table([m], columns)]
    if m.get("small_sample"):
        parts.append("\n_Small sample: rates are unstable._")
    if note:
        parts.append(f"\n_{note}_")
    if lg:
        parts.append(f"\n_cFIP {lg.fip_constant:.2f}, league ERA {lg.era:.2f} ({lg.source})._")
    return "\n".join(parts)


@mcp.tool(name="baseball_leaderboard", title="Season leaderboard", annotations=READ_ONLY_REMOTE)
async def baseball_leaderboard(
    sort_by: Annotated[str, Field(description=(
        "Metric to rank by. Hitting: " + ", ".join(BATTING_SORT_KEYS)
        + ". Pitching: " + ", ".join(PITCHING_SORT_KEYS) + "."))],
    league: Annotated[League, Field(description="Which league's data to use.")] = "MLB",
    season: Annotated[int | None, Field(description="Season year. Default: current MLB season / latest KBO file.", ge=1876, le=2100)] = None,
    group: Annotated[Group, Field(description="'hitting' or 'pitching'.")] = "hitting",
    limit: Annotated[int, Field(description="Rows to return.", ge=1, le=50)] = 10,
    qualified: Annotated[bool, Field(description="Only rate-qualified players (3.1 PA / 1.0 IP per team game).")] = True,
    min_pa: Annotated[int | None, Field(description="Extra minimum PA filter (hitting).", ge=0)] = None,
    min_ip: Annotated[float | None, Field(description="Extra minimum IP filter (pitching).", ge=0)] = None,
    team: Annotated[str | None, Field(description="Only players whose team contains this text.")] = None,
    ascending: Annotated[bool | None, Field(description="Override sort direction. Default: best first (low ERA/FIP/WHIP, high OPS...).")] = None,
    format: Annotated[Format, Field(description="'markdown' (default) or 'json'.")] = "markdown",
) -> str:
    """Rank players by any computed metric, including ones the source does not publish (FIP, K-BB%, LOB%, ISO...)."""
    keys = BATTING_SORT_KEYS if group == "hitting" else PITCHING_SORT_KEYS
    if sort_by not in keys:
        raise ToolError(f"sort_by '{sort_by}' is not valid for {group}. Choose one of: {', '.join(keys)}.")
    try:
        season_ = _season(league, season, group)
        src = _source(league)
        lines, pool_note = await src.season_lines(season_, group, qualified)
        lg, note = (None, None) if group == "hitting" else await _context_or_none(src, season_)
    except DataError as e:
        raise _tool_error(e) from e

    rows = []
    for line in lines:
        if team and team.lower() not in line.team.lower():
            continue
        m = batting_metrics(line) if group == "hitting" else pitching_metrics(line, lg)
        if min_pa is not None and group == "hitting" and m["pa"] < min_pa:
            continue
        if min_ip is not None and group == "pitching" and m["ip"] < min_ip:
            continue
        if m.get(sort_by) is None:
            continue
        rows.append({"name": line.name, "team": line.team, **m})

    asc = ascending if ascending is not None else sort_by in (BATTING_ASCENDING if group == "hitting" else PITCHING_ASCENDING)
    rows.sort(key=lambda r: r[sort_by], reverse=not asc)
    rows = rows[:limit]
    if not rows:
        raise ToolError(f"No players left after filters ({pool_note}). Try qualified=false or lower min_pa/min_ip.")

    if format == "json":
        return F.to_json({"league": league, "season": season_, "group": group, "sort_by": sort_by,
                          "pool": pool_note, "league_context": lg.as_dict() if lg else None, "rows": rows})
    base_cols = F.BATTING_COLUMNS if group == "hitting" else F.PITCHING_COLUMNS
    columns = ["name", "team", *base_cols]
    if sort_by in keys and sort_by not in columns and sort_by != "ip":
        columns.append(sort_by)
    out = [f"**{league} {season_} {group} leaders by {F.LABELS.get(sort_by, sort_by)}** - {pool_note}", "", F.table(rows, columns)]
    if note:
        out.append(f"\n_{note}_")
    return "\n".join(out)


@mcp.tool(name="baseball_pitcher_luck_check", title="Pitcher luck check (ERA vs FIP, BABIP, LOB%)", annotations=READ_ONLY_REMOTE)
async def baseball_pitcher_luck_check(
    player: Annotated[str, Field(description="MLB: English name or id. KBO: Korean name as in the CSV.", min_length=1)],
    league: Annotated[League, Field(description="Which league's data to use.")] = "MLB",
    season: Annotated[int | None, Field(description="Season year. Default: current MLB season / latest KBO file.", ge=1876, le=2100)] = None,
    team: Annotated[str | None, Field(description="Optional team filter.")] = None,
    format: Annotated[Format, Field(description="'markdown' (default) or 'json'.")] = "markdown",
) -> str:
    """Is a pitcher's ERA lucky or unlucky? Compares ERA to FIP, then BABIP and LOB% to the league.

    Returns the gaps, plain-language signals, an overall verdict, and caveats (sample size,
    contact quality, defense). Signals are leads to investigate, not conclusions.
    """
    try:
        season_ = _season(league, season, "pitching")
        src = _source(league)
        line = await src.player_line(player, season_, "pitching", team)
        lg = await src.league_context(season_)
    except DataError as e:
        raise _tool_error(e) from e
    result = luck_check(line, lg)

    if format == "json":
        return F.to_json({"league": league, "season": season_, "player": line.name, "team": line.team, **result})
    m = result["metrics"]
    compare = [
        {"name": line.name, "era": m["era"], "fip": m["fip"], "babip": m["babip"], "lob_pct": m["lob_pct"], "k_minus_bb_pct": m["k_minus_bb_pct"]},
        {"name": f"{league} avg", "era": lg.era, "fip": lg.era, "babip": lg.babip, "lob_pct": lg.lob_pct,
         "k_minus_bb_pct": (lg.k_pct - lg.bb_pct) if lg.k_pct is not None and lg.bb_pct is not None else None},
    ]
    out = [
        f"**{line.name}** ({line.team or 'team n/a'}) - {league} {season_}, {m['ip_display']} IP",
        "",
        F.table(compare, ["name", "era", "fip", "babip", "lob_pct", "k_minus_bb_pct"]),
        "",
        f"**Verdict:** {result['verdict']}",
    ]
    if result["signals"]:
        out += ["", "**Signals**", *[f"- {s}" for s in result["signals"]]]
    out += ["", "**Caveats**", *[f"- {c}" for c in result["caveats"]]]
    out.append(f"\n_League baseline: {lg.source}; cFIP {lg.fip_constant:.2f}._")
    return "\n".join(out)


@mcp.tool(name="mlb_search_players", title="Search MLB players", annotations=READ_ONLY_REMOTE)
async def mlb_search_players(
    name: Annotated[str, Field(description="Full or partial English name, e.g. 'Kim', 'Ohtani'.", min_length=2)],
    limit: Annotated[int, Field(description="Max results.", ge=1, le=25)] = 10,
) -> str:
    """Find MLB player ids by name. Use the id with the other tools when a name is ambiguous."""
    try:
        players = await SOURCES["MLB"].search_players(name, limit)
    except DataError as e:
        raise _tool_error(e) from e
    if not players:
        return f"No MLB players matched '{name}'. Try the surname only, in English."
    return F.table(players, ["id", "name", "position", "bats", "throws", "active", "mlb_debut"])


@mcp.tool(name="mlb_standings", title="MLB standings with Pythagorean record", annotations=READ_ONLY_REMOTE)
async def mlb_standings(
    season: Annotated[int | None, Field(description="Season year. Default: current season.", ge=1901, le=2100)] = None,
    exponent: Annotated[float, Field(description="Pythagorean exponent (1.83 is the common choice; 2.0 is Bill James' original).", ge=1.0, le=3.0)] = 1.83,
    format: Annotated[Format, Field(description="'markdown' (default) or 'json'.")] = "markdown",
) -> str:
    """Regular-season standings by division, with run differential, Pythagorean expected wins,
    and luck (actual wins minus expected)."""
    season_ = season or default_mlb_season()
    try:
        divisions = await SOURCES["MLB"].standings(season_)
    except DataError as e:
        raise _tool_error(e) from e
    for d in divisions:
        for t in d["teams"]:
            pct, exp_w = pythagorean(t["rs"], t["ra"], t["w"] + t["l"], exponent)
            t["pythag_pct"] = pct
            t["pythag_w"] = round(exp_w, 1) if exp_w is not None else None
            t["luck"] = round(t["w"] - exp_w, 1) if exp_w is not None else None
    if format == "json":
        return F.to_json({"season": season_, "exponent": exponent, "divisions": divisions})
    out = [f"**MLB {season_} standings** (Pythagorean exponent {exponent})"]
    for d in divisions:
        out += ["", f"**{d['division']}**",
                F.table(d["teams"], ["team", "w", "l", "pct", "gb", "rs", "ra", "diff", "pythag_w", "luck", "streak"])]
    return "\n".join(out)


@mcp.tool(name="kbo_data_status", title="KBO data files status", annotations=READ_ONLY_LOCAL)
async def kbo_data_status() -> str:
    """Show which KBO CSV files are loaded, their row counts, any column problems, and the expected file names."""
    return F.to_json(SOURCES["KBO"].status())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
