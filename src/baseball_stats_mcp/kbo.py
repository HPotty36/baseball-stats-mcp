"""KBO data from local CSV files.

The official KBO site (koreabaseball.com) disallows automated access in its
robots.txt, so this server does not scrape it. Instead you drop season CSVs into
a folder and the server reads them:

    <KBO_DATA_DIR>/hitters_2026.csv
    <KBO_DATA_DIR>/pitchers_2026.csv
    <KBO_DATA_DIR>/league_overrides.json   (optional, e.g. {"2026": {"fip_constant": 4.21}})

Column headers may be Korean (as on the KBO site) or English; see COLUMN_ALIASES.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .errors import DataError
from .lines import BattingLine, PitchingLine, combine, parse_ip
from .metrics import LeagueContext

ENCODINGS = ("utf-8-sig", "cp949")  # Excel on Korean Windows saves CSV as cp949
DEFAULT_TEAM_GAMES = 144
FILE_PATTERN = re.compile(r"^(hitters|pitchers)_(\d{4})\.csv$")

# canonical field -> accepted headers (compared case-insensitively, spaces removed)
COLUMN_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "hitting": {
        "name": ("선수명", "이름", "name", "player"),
        "team": ("팀명", "팀", "team"),
        "G": ("G", "경기"),
        "PA": ("PA", "타석"),
        "AB": ("AB", "타수"),
        "R": ("R", "득점"),
        "H": ("H", "안타"),
        "doubles": ("2B", "2루타"),
        "triples": ("3B", "3루타"),
        "HR": ("HR", "홈런"),
        "RBI": ("RBI", "타점"),
        "SB": ("SB", "도루"),
        "CS": ("CS", "도루실패"),
        "BB": ("BB", "볼넷"),
        "IBB": ("IBB", "고의4구", "고의사구"),
        "HBP": ("HBP", "사구", "몸에맞는공"),
        "SO": ("SO", "K", "삼진"),
        "SF": ("SF", "희생플라이", "희비"),
        "SH": ("SAC", "SH", "희생번트", "희타"),
        "GDP": ("GDP", "병살타", "병살"),
    },
    "pitching": {
        "name": ("선수명", "이름", "name", "player"),
        "team": ("팀명", "팀", "team"),
        "G": ("G", "경기"),
        "GS": ("GS", "선발"),
        "W": ("W", "승"),
        "L": ("L", "패"),
        "SV": ("SV", "세이브"),
        "HLD": ("HLD", "홀드"),
        "IP": ("IP", "이닝"),
        "BF": ("TBF", "BF", "타자", "상대타자"),
        "AB": ("AB", "타수", "피타수"),
        "H": ("H", "피안타"),
        "HR": ("HR", "피홈런"),
        "BB": ("BB", "볼넷"),
        "IBB": ("IBB", "고의4구", "고의사구"),
        "HBP": ("HBP", "사구", "몸에맞는공"),
        "SO": ("SO", "K", "탈삼진", "삼진"),
        "R": ("R", "실점"),
        "ER": ("ER", "자책점"),
        "SF": ("SF", "희생플라이"),
    },
}
REQUIRED = {
    "hitting": ("name", "AB", "H", "HR", "BB", "SO"),
    "pitching": ("name", "IP", "H", "HR", "BB", "SO", "ER"),
}


def _norm(header: str) -> str:
    return re.sub(r"\s+", "", header).lower()


def _to_int(value: str | None) -> int:
    if value is None:
        return 0
    s = str(value).strip().replace(",", "")
    if s in ("", "-"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DataError(f"{path.name}: could not decode as UTF-8 or CP949. Re-save the CSV as UTF-8.")


def _map_headers(headers: list[str], group: str) -> tuple[dict[str, str], list[str]]:
    """Return (canonical -> actual header, missing required canonical fields)."""
    lookup = {_norm(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES[group].items():
        for alias in aliases:
            if _norm(alias) in lookup:
                mapping[field] = lookup[_norm(alias)]
                break
    missing = [f for f in REQUIRED[group] if f not in mapping]
    return mapping, missing


def _row_to_line(row: dict[str, str], mapping: dict[str, str], group: str, season: str) -> BattingLine | PitchingLine:
    get = lambda field: row.get(mapping[field]) if field in mapping else None  # noqa: E731
    name = (get("name") or "").strip()
    team = (get("team") or "").strip()
    if group == "hitting":
        counting = [f for f in COLUMN_ALIASES["hitting"] if f not in ("name", "team")]
        return BattingLine(name=name, team=team, season=season, **{f: _to_int(get(f)) for f in counting})
    counting = [f for f in COLUMN_ALIASES["pitching"] if f not in ("name", "team", "IP")]
    return PitchingLine(
        name=name, team=team, season=season, outs=parse_ip(get("IP")), **{f: _to_int(get(f)) for f in counting}
    )


class KBOSource:
    league = "KBO"

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._cache: dict[Path, tuple[float, list[Any], list[str]]] = {}

    # ---- files ---------------------------------------------------------

    def _path(self, season: int, group: str) -> Path:
        prefix = "hitters" if group == "hitting" else "pitchers"
        return self.data_dir / f"{prefix}_{season}.csv"

    def available(self) -> dict[str, list[int]]:
        found: dict[str, list[int]] = {"hitting": [], "pitching": []}
        if self.data_dir.is_dir():
            for p in self.data_dir.iterdir():
                m = FILE_PATTERN.match(p.name)
                if m:
                    found["hitting" if m.group(1) == "hitters" else "pitching"].append(int(m.group(2)))
        return {k: sorted(v) for k, v in found.items()}

    def latest_season(self, group: str) -> int:
        seasons = self.available()[group]
        if not seasons:
            raise DataError(self._no_data_message(None, group))
        return seasons[-1]

    def _no_data_message(self, season: int | None, group: str) -> str:
        prefix = "hitters" if group == "hitting" else "pitchers"
        name = f"{prefix}_{season}.csv" if season else f"{prefix}_<season>.csv"
        return (
            f"No KBO {group} data: expected {self.data_dir / name}. "
            "Export the season table to CSV and save it there (see data/kbo/README.md), "
            "or call kbo_data_status to see what is loaded."
        )

    def load(self, season: int, group: str) -> list[BattingLine | PitchingLine]:
        path = self._path(season, group)
        if not path.is_file():
            raise DataError(self._no_data_message(season, group))
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        reader = csv.DictReader(io.StringIO(_read_text(path)))
        mapping, missing = _map_headers(reader.fieldnames or [], group)
        if missing:
            raise DataError(
                f"{path.name} is missing required columns {missing}. Found headers: {reader.fieldnames}. "
                "If you copied two KBO tables (e.g. 기본기록 1 and 2), merge them into one CSV per player."
            )
        lines = [_row_to_line(r, mapping, group, str(season)) for r in reader]
        lines = [l for l in lines if l.name]
        unmapped = [h for h in (reader.fieldnames or []) if h and h not in mapping.values()]
        self._cache[path] = (mtime, lines, unmapped)
        return lines

    def _overrides(self, season: int) -> dict[str, Any]:
        path = self.data_dir / "league_overrides.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise DataError(f"league_overrides.json is not valid JSON: {e}") from e
        return data.get(str(season), {})

    def team_games(self, season: int) -> tuple[int, str]:
        override = self._overrides(season).get("team_games")
        if override:
            return int(override), "league_overrides.json"
        try:
            hitters = self.load(season, "hitting")
        except DataError:
            return DEFAULT_TEAM_GAMES, "default (no hitters file)"
        most = max((h.G for h in hitters), default=0)
        return (most, "max G in hitters file") if most else (DEFAULT_TEAM_GAMES, "default")

    # ---- StatsSource interface ------------------------------------------

    async def player_line(
        self, player: str, season: int, group: str, team: str | None = None
    ) -> BattingLine | PitchingLine:
        lines = self.load(season, group)
        query = player.strip()
        matches = [l for l in lines if l.name == query] or [l for l in lines if query in l.name]
        if team:
            matches = [l for l in matches if team in l.team]
        if not matches:
            raise DataError(f"No KBO player matching '{query}' in the {season} {group} file. Use the Korean name as in the CSV.")
        if len({(l.name, l.team) for l in matches}) > 1:
            listing = ", ".join(f"{l.name} ({l.team})" for l in matches[:10])
            raise DataError(f"'{query}' matches several KBO players: {listing}. Pass the exact name and/or team.")
        return combine(matches) if len(matches) > 1 else matches[0]

    async def season_lines(
        self, season: int, group: str, qualified: bool = True
    ) -> tuple[list[BattingLine | PitchingLine], str]:
        lines = self.load(season, group)
        if not qualified:
            return lines, f"All {len(lines)} players in {self._path(season, group).name}"
        games, how = self.team_games(season)
        if group == "hitting":
            cutoff = 3.1 * games
            kept = [l for l in lines if (l.PA or l.AB + l.BB + l.HBP + l.SF + l.SH) >= cutoff]
            return kept, f"KBO qualified: PA >= 3.1 x {games} team games ({how})"
        kept = [l for l in lines if l.ip >= games]
        return kept, f"KBO qualified: IP >= 1 x {games} team games ({how})"

    async def league_context(self, season: int) -> LeagueContext:
        pitchers = self.load(season, "pitching")
        totals = combine(pitchers)
        if not totals.outs:
            raise DataError(f"pitchers_{season}.csv has no innings pitched; cannot compute league baselines.")
        override = self._overrides(season).get("fip_constant")
        source = f"Sum of {len(pitchers)} pitchers in pitchers_{season}.csv"
        if override is not None:
            source += "; FIP constant from league_overrides.json"
        else:
            source += " (FIP constant is biased if the file holds only some pitchers)"
        return LeagueContext.from_totals(
            totals, league="KBO", season=str(season), source=source, fip_constant_override=override
        )

    # ---- status ----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        files = []
        for group, seasons in self.available().items():
            for season in seasons:
                entry: dict[str, Any] = {"file": self._path(season, group).name, "group": group, "season": season}
                try:
                    lines = self.load(season, group)
                    entry["rows"] = len(lines)
                    entry["ignored_columns"] = self._cache[self._path(season, group)][2]
                except DataError as e:
                    entry["error"] = str(e)
                files.append(entry)
        return {
            "data_dir": str(self.data_dir),
            "data_dir_exists": self.data_dir.is_dir(),
            "files": files,
            "expected_names": ["hitters_<season>.csv", "pitchers_<season>.csv", "league_overrides.json (optional)"],
            "required_columns": {g: list(c) for g, c in REQUIRED.items()},
        }
