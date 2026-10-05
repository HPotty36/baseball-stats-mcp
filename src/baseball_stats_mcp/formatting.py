"""Turn metric dicts into compact markdown (default) or JSON for the model."""

from __future__ import annotations

import json
from typing import Any

RATE3 = {"avg", "obp", "slg", "ops", "iso", "babip", "pct", "pythag_pct"}
PCT = {"bb_pct", "k_pct", "k_minus_bb_pct", "lob_pct", "hr_pct"}
TWO_DP = {"era", "fip", "era_minus_fip", "ra9", "whip", "k9", "bb9", "hr9", "bb_k", "fip_constant"}
SIGNED_RATE3 = {"babip_vs_league"}
SIGNED_PCT = {"lob_pct_vs_league"}
ONE_DP = {"pythag_w"}
SIGNED_ONE_DP = {"luck"}

LABELS = {
    "name": "Player", "team": "Team", "g": "G", "gs": "GS", "w": "W", "l": "L", "sv": "SV",
    "hld": "HLD", "pa": "PA", "ab": "AB", "h": "H", "hr": "HR", "rbi": "RBI", "sb": "SB",
    "bb": "BB", "so": "SO", "avg": "AVG", "obp": "OBP", "slg": "SLG", "ops": "OPS", "iso": "ISO",
    "babip": "BABIP", "bb_pct": "BB%", "k_pct": "K%", "bb_k": "BB/K", "hr_pct": "HR%",
    "ip_display": "IP", "bf": "BF", "era": "ERA", "fip": "FIP", "era_minus_fip": "ERA-FIP",
    "ra9": "RA9", "whip": "WHIP", "k9": "K/9", "bb9": "BB/9", "hr9": "HR/9",
    "k_minus_bb_pct": "K-BB%", "lob_pct": "LOB%", "fip_constant": "cFIP",
}


def fmt(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    if key in RATE3:
        s = f"{value:.3f}"
        return s[1:] if s.startswith("0.") else s
    if key in PCT:
        return f"{value * 100:.1f}%"
    if key in TWO_DP:
        return f"{value:.2f}"
    if key in SIGNED_RATE3:
        return f"{value:+.3f}"
    if key in SIGNED_PCT:
        return f"{value * 100:+.1f} pts"
    if key in ONE_DP:
        return f"{value:.1f}"
    if key in SIGNED_ONE_DP:
        return f"{value:+.1f}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    header = "| " + " | ".join(LABELS.get(c, c) for c in columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(fmt(c, r.get(c)) for c in columns) + " |" for r in rows]
    return "\n".join([header, sep, *body])


def to_json(payload: Any) -> str:
    def clean(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v

    return json.dumps(clean(payload), ensure_ascii=False, indent=2)


BATTING_COLUMNS = ["g", "pa", "avg", "obp", "slg", "ops", "iso", "babip", "bb_pct", "k_pct", "hr", "sb"]
PITCHING_COLUMNS = [
    "g", "gs", "ip_display", "era", "fip", "era_minus_fip", "whip", "k_pct", "bb_pct",
    "k_minus_bb_pct", "babip", "lob_pct", "hr9",
]
