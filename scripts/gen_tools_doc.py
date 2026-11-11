"""Regenerate the tool table in docs/TOOLS.md from the contract snapshots (single source of truth).

    uv run python -m scripts.gen_tools_doc
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "tests" / "contract" / "snapshots"
DOC = ROOT / "docs" / "TOOLS.md"
AUTH = {"marketplace": "Bearer (HTTP); read: `marketplace:read`, write: `marketplace:write`",
        "portfolio": "Bearer (HTTP), `portfolio:read`; tenant = persona of the token's user",
        "workspace": "Bearer (HTTP); read: `workspace:read`, write: `workspace:write`"}
OWNER = {"marketplace": "Scout, Risk, Pricing, Liaison (read); executor node (write)",
         "portfolio": "Fit Matcher, Writer, Critic", "workspace": "Liaison (read); executor node (write)"}


def ann(a: dict | None) -> str:
    if not a:
        return ""
    flags = [k.replace("Hint", "") for k in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint") if a.get(k)]
    return ", ".join(flags)


def table() -> str:
    rows = ["| Tool | Server | Read/Write | Annotations | Auth | Used by | Description |", "|---|---|---|---|---|---|---|"]
    for server in ("marketplace", "portfolio", "workspace"):
        snap = json.loads((SNAP / f"{server}.json").read_text(encoding="utf-8"))
        for name, t in snap["tools"].items():
            rw = "read" if (t["annotations"] or {}).get("readOnlyHint") else "write"
            desc = (t["description"] or "").strip().split("\n")[0]
            rows.append(f"| `{name}` | {server} | {rw} | {ann(t['annotations'])} | {AUTH[server]} | {OWNER[server]} | {desc} |")
        for r in snap["resource_templates"] + snap["resources"]:
            rows.append(f"| `{r}` (resource) | {server} | read | - | {AUTH[server]} | MCP hosts | resource |")
        for p, args in snap["prompts"].items():
            rows.append(f"| `{p}({', '.join(args)})` (prompt) | {server} | - | - | - | MCP hosts | prompt template |")
    return "\n".join(rows)


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    new = re.sub(r"<!-- TOOLS:BEGIN -->.*<!-- TOOLS:END -->",
                 "<!-- TOOLS:BEGIN -->\n" + table() + "\n<!-- TOOLS:END -->", text, flags=re.DOTALL)
    DOC.write_text(new, encoding="utf-8")
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
