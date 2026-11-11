"""Render both LangGraph graphs from code to Mermaid (docs/images/*.mmd), embedded in docs/ARCHITECTURE.md.

    uv run python -m scripts.render_graphs
"""
from __future__ import annotations

from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.nodes.common import Deps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    deps = Deps(toolbox=None)
    for name, g in (("bid_graph", build_bid_graph(deps)), ("conversation_graph", build_conversation_graph(deps))):
        mmd = g.get_graph().draw_mermaid()
        (OUT / f"{name}.mmd").write_text(mmd, encoding="utf-8")
        print(f"wrote docs/images/{name}.mmd ({len(mmd.splitlines())} lines)")


if __name__ == "__main__":
    main()
