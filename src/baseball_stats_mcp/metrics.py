"""Sabermetric calculations on league-agnostic stat lines.

Formulas follow the common FanGraphs-style definitions:
  FIP   = (13*HR + 3*(BB+HBP) - 2*K) / IP + cFIP
  cFIP  = lgERA - (13*lgHR + 3*(lgBB+lgHBP) - 2*lgK) / lgIP
  BABIP = (H - HR) / (AB - K - HR + SF)
  LOB%  = (H + BB + HBP - R) / (H + BB + HBP - 1.4*HR)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .lines import BattingLine, PitchingLine

# Thresholds used by the luck check. Deliberately coarse: they flag where to look,
# they do not prove anything on their own.
ERA_FIP_GAP = 0.75
BABIP_GAP = 0.030
LOB_GAP = 0.05
SMALL_SAMPLE_IP = 40.0
SMALL_SAMPLE_PA = 150

BATTING_SORT_KEYS = (
    "ops", "obp", "slg", "avg", "iso", "babip", "bb_pct", "k_pct", "bb_k",
    "hr", "hr_pct", "sb", "pa",
)
PITCHING_SORT_KEYS = (
    "fip", "era", "era_minus_fip", "whip", "k_pct", "bb_pct", "k_minus_bb_pct",
    "k9", "bb9", "hr9", "babip", "lob_pct", "ip", "so",
)
# Lower is better for these, so leaderboards sort them ascending by default.
BATTING_ASCENDING = {"k_pct"}
PITCHING_ASCENDING = {"era", "fip", "whip", "bb_pct", "bb9", "hr9"}


def _div(n: float, d: float) -> float | None:
    return n / d if d else None


def _sub(a: float | None, b: float | None) -> float | None:
    return a - b if a is not None and b is not None else None


def batting_metrics(b: BattingLine) -> dict[str, Any]:
    pa = b.PA or (b.AB + b.BB + b.HBP + b.SF + b.SH)
    singles = b.H - b.doubles - b.triples - b.HR
    tb = singles + 2 * b.doubles + 3 * b.triples + 4 * b.HR
    avg = _div(b.H, b.AB)
    obp = _div(b.H + b.BB + b.HBP, b.AB + b.BB + b.HBP + b.SF)
    slg = _div(tb, b.AB)
    return {
        "g": b.G,
        "pa": pa,
        "ab": b.AB,
        "h": b.H,
        "hr": b.HR,
        "rbi": b.RBI,
        "sb": b.SB,
        "bb": b.BB,
        "so": b.SO,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": obp + slg if obp is not None and slg is not None else None,
        "iso": _sub(slg, avg),
        "babip": _div(b.H - b.HR, b.AB - b.SO - b.HR + b.SF),
        "bb_pct": _div(b.BB, pa),
        "k_pct": _div(b.SO, pa),
        "bb_k": _div(b.BB, b.SO),
        "hr_pct": _div(b.HR, pa),
        "small_sample": pa < SMALL_SAMPLE_PA,
    }


def pitcher_babip(p: PitchingLine) -> tuple[float | None, bool]:
    """Return (BABIP, is_approximate). Falls back to batters faced if AB is missing."""
    if p.AB:
        return _div(p.H - p.HR, p.AB - p.SO - p.HR + p.SF), False
    return _div(p.H - p.HR, p.BF - p.SO - p.HR - p.BB - p.HBP - p.SF), True


def lob_pct(p: PitchingLine) -> float | None:
    return _div(p.H + p.BB + p.HBP - p.R, p.H + p.BB + p.HBP - 1.4 * p.HR)


def _fip_core(p: PitchingLine) -> float | None:
    return _div(13 * p.HR + 3 * (p.BB + p.HBP) - 2 * p.SO, p.ip)


@dataclass
class LeagueContext:
    """League-wide pitching baselines for one season."""

    league: str
    season: str
    source: str  # human-readable description of where the totals came from
    era: float
    fip_constant: float
    babip: float | None
    lob_pct: float | None
    k_pct: float | None
    bb_pct: float | None

    @classmethod
    def from_totals(
        cls,
        totals: PitchingLine,
        *,
        league: str,
        season: str,
        source: str,
        fip_constant_override: float | None = None,
    ) -> "LeagueContext":
        era = 9 * totals.ER / totals.ip
        core = _fip_core(totals) or 0.0
        return cls(
            league=league,
            season=season,
            source=source,
            era=era,
            fip_constant=fip_constant_override if fip_constant_override is not None else era - core,
            babip=pitcher_babip(totals)[0],
            lob_pct=lob_pct(totals),
            k_pct=_div(totals.SO, totals.BF),
            bb_pct=_div(totals.BB, totals.BF),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pitching_metrics(p: PitchingLine, lg: LeagueContext | None = None) -> dict[str, Any]:
    ip = p.ip
    era = _div(9 * p.ER, ip)
    k_pct = _div(p.SO, p.BF)
    bb_pct = _div(p.BB, p.BF)
    babip, babip_approx = pitcher_babip(p)
    core = _fip_core(p)
    fip = core + lg.fip_constant if core is not None and lg is not None else None
    return {
        "g": p.G,
        "gs": p.GS,
        "w": p.W,
        "l": p.L,
        "sv": p.SV,
        "hld": p.HLD,
        "ip": round(ip, 3),
        "ip_display": p.ip_display,
        "bf": p.BF,
        "so": p.SO,
        "bb": p.BB,
        "hr": p.HR,
        "era": era,
        "fip": fip,
        "era_minus_fip": _sub(era, fip),
        "ra9": _div(9 * p.R, ip),
        "whip": _div(p.BB + p.H, ip),
        "k9": _div(9 * p.SO, ip),
        "bb9": _div(9 * p.BB, ip),
        "hr9": _div(9 * p.HR, ip),
        "k_pct": k_pct,
        "bb_pct": bb_pct,
        "k_minus_bb_pct": _sub(k_pct, bb_pct),
        "babip": babip,
        "babip_is_approx": babip_approx,
        "lob_pct": lob_pct(p),
        "small_sample": ip < SMALL_SAMPLE_IP,
    }


def luck_check(p: PitchingLine, lg: LeagueContext) -> dict[str, Any]:
    """ERA vs FIP gap, then BABIP and LOB% against league, as signals to investigate."""
    m = pitching_metrics(p, lg)
    signals: list[str] = []
    direction = 0  # >0: ERA likely to improve, <0: ERA likely to get worse

    gap = m["era_minus_fip"]
    if gap is not None and gap >= ERA_FIP_GAP:
        direction += 1
        signals.append(f"ERA is {gap:.2f} runs above FIP: run prevention has trailed the K/BB/HR peripherals.")
    elif gap is not None and gap <= -ERA_FIP_GAP:
        direction -= 1
        signals.append(f"ERA is {-gap:.2f} runs below FIP: results have outrun the K/BB/HR peripherals.")

    babip_diff = _sub(m["babip"], lg.babip)
    if babip_diff is not None and babip_diff >= BABIP_GAP:
        direction += 1
        signals.append(f"BABIP is {babip_diff * 1000:+.0f} points vs league: more balls in play falling for hits than usual.")
    elif babip_diff is not None and babip_diff <= -BABIP_GAP:
        direction -= 1
        signals.append(f"BABIP is {babip_diff * 1000:+.0f} points vs league: fewer balls in play falling for hits than usual.")

    lob_diff = _sub(m["lob_pct"], lg.lob_pct)
    if lob_diff is not None and lob_diff >= LOB_GAP:
        direction -= 1
        signals.append(f"LOB% is {lob_diff * 100:+.1f} pts vs league: stranding runners at an unusually high rate.")
    elif lob_diff is not None and lob_diff <= -LOB_GAP:
        direction += 1
        signals.append(f"LOB% is {lob_diff * 100:+.1f} pts vs league: stranding runners at an unusually low rate.")

    if direction > 0:
        verdict = "ERA looks worse than the underlying performance; positive regression is plausible."
    elif direction < 0:
        verdict = "ERA looks better than the underlying performance; negative regression is plausible."
    else:
        verdict = "No strong luck signal: ERA is roughly in line with peripherals and league baselines."

    contact = (
        "Check Statcast (xERA, hard-hit%, barrel%)"
        if lg.league == "MLB"
        else "Check batted-ball/contact-quality data where available"
    )
    caveats = [
        f"FIP ignores contact quality. {contact} before calling it luck.",
        "Team defense and park factors also move BABIP and ERA.",
    ]
    if m["small_sample"]:
        caveats.insert(0, f"Small sample: {m['ip_display']} IP (< {SMALL_SAMPLE_IP:.0f}). Treat all signals as noise-prone.")
    if m["babip_is_approx"]:
        caveats.append("BABIP is approximated from batters faced because at-bats against were not available.")

    return {
        "metrics": m,
        "league": lg.as_dict(),
        "deltas": {
            "era_minus_fip": gap,
            "babip_vs_league": babip_diff,
            "lob_pct_vs_league": lob_diff,
        },
        "signals": signals,
        "verdict": verdict,
        "caveats": caveats,
    }


def pythagorean(rs: int, ra: int, games: int, exponent: float = 1.83) -> tuple[float | None, float | None]:
    """Return (expected win pct, expected wins)."""
    if rs <= 0 and ra <= 0:
        return None, None
    pct = rs**exponent / (rs**exponent + ra**exponent)
    return pct, pct * games
