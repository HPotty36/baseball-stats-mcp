"""League-agnostic stat lines.

Every data source (MLB Stats API, KBO CSV, ...) converts its raw rows into these
two dataclasses, so the metric code in ``metrics.py`` never needs to know where
the numbers came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import TypeVar, Union

from .errors import DataError


@dataclass
class BattingLine:
    name: str
    team: str = ""
    season: str = ""
    player_id: str | None = None
    G: int = 0
    PA: int = 0
    AB: int = 0
    R: int = 0
    H: int = 0
    doubles: int = 0
    triples: int = 0
    HR: int = 0
    RBI: int = 0
    SB: int = 0
    CS: int = 0
    BB: int = 0
    IBB: int = 0
    HBP: int = 0
    SO: int = 0
    SF: int = 0
    SH: int = 0
    GDP: int = 0


@dataclass
class PitchingLine:
    name: str
    team: str = ""
    season: str = ""
    player_id: str | None = None
    G: int = 0
    GS: int = 0
    W: int = 0
    L: int = 0
    SV: int = 0
    HLD: int = 0
    outs: int = 0  # innings pitched stored as outs to avoid the ".1 = 1/3" trap
    BF: int = 0
    AB: int = 0  # at-bats against; some sources lack it (BABIP falls back to BF)
    H: int = 0
    HR: int = 0
    BB: int = 0
    IBB: int = 0
    HBP: int = 0
    SO: int = 0
    R: int = 0
    ER: int = 0
    SF: int = 0

    @property
    def ip(self) -> float:
        return self.outs / 3

    @property
    def ip_display(self) -> str:
        return f"{self.outs // 3}.{self.outs % 3}"


Line = Union[BattingLine, PitchingLine]
L = TypeVar("L", BattingLine, PitchingLine)

_IDENTITY_FIELDS = {"name", "team", "season", "player_id"}
_UNICODE_THIRDS = {"⅓": 1, "⅔": 2}


def combine(lines: list[L]) -> L:
    """Sum counting stats across splits (e.g. a player traded mid-season)."""
    if not lines:
        raise ValueError("combine() needs at least one line")
    first = lines[0]
    cls = type(first)
    totals: dict[str, object] = {
        "name": first.name,
        "season": first.season,
        "player_id": first.player_id,
        "team": "/".join(dict.fromkeys(l.team for l in lines if l.team)),
    }
    for f in fields(cls):
        if f.name not in _IDENTITY_FIELDS:
            totals[f.name] = sum(getattr(l, f.name) for l in lines)
    return cls(**totals)  # type: ignore[arg-type]


def parse_ip(value: object) -> int:
    """Convert an innings-pitched value to outs.

    Accepts baseball notation ("144.1" = 144 1/3), KBO-style fractions
    ("144 1/3", "1/3"), unicode thirds ("144⅓") and true decimals ("144.33").
    """
    if value is None:
        return 0
    s = str(value).strip().replace(",", "")
    if s in ("", "-"):
        return 0
    for ch, thirds in _UNICODE_THIRDS.items():
        if ch in s:
            whole = s.replace(ch, "").strip()
            return (int(whole) if whole else 0) * 3 + thirds
    m = re.fullmatch(r"(?:(\d+)\s+)?(\d)/3", s)
    if m:
        return int(m.group(1) or 0) * 3 + int(m.group(2))
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", s)
    if not m:
        raise DataError(f"Could not parse innings pitched value {value!r}.")
    whole, frac = int(m.group(1)), m.group(2)
    if not frac:
        return whole * 3
    if frac in ("0", "1", "2"):
        return whole * 3 + int(frac)
    return whole * 3 + round(float("0." + frac) * 3)
