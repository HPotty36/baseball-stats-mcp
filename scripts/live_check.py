"""Live smoke test: launch the server over stdio (like Claude does) and call MLB tools
against the real MLB Stats API.  Run:  uv run python scripts/live_check.py
"""

import asyncio
import sys

from mcp import Client, StdioServerParameters

CALLS = [
    ("mlb_search_players", {"name": "Ha-Seong Kim"}),
    ("baseball_player_stats", {"player": "Shohei Ohtani", "season": 2025}),
    ("baseball_pitcher_luck_check", {"player": "Bryce Elder", "season": 2025}),
    ("baseball_leaderboard", {"group": "pitching", "sort_by": "k_minus_bb_pct", "limit": 5}),
    ("baseball_leaderboard", {"group": "hitting", "sort_by": "iso", "limit": 5, "team": "Braves", "qualified": False, "min_pa": 200}),
    ("mlb_standings", {}),
    ("kbo_data_status", {}),
]


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "baseball_stats_mcp"])
    failures = 0
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
        print(f"tools: {', '.join(t.name for t in tools)}\n")
        for name, args in CALLS:
            r = await client.call_tool(name, args)
            failures += bool(r.is_error)
            print(f"### {name} {args} -> {'ERROR' if r.is_error else 'ok'}")
            print("\n".join(c.text for c in r.content if getattr(c, "text", None)))
            print()
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
