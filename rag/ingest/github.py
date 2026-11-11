"""Ingest a freelancer's GitHub repos through the official GitHub MCP server (A5, B1).

Writes each repo into the portfolio folder layout (repos/<name>/README.md + code files) so the Portfolio
server's incremental re-index picks it up. Only read tools are used, via the `ingestion` allowlist.

    GITHUB_TOKEN=... uv run python -m rag.ingest.github --owner <user> --persona ai_ml [--max-repos 5]

Requires a GitHub token (read-only scopes are enough). Not exercised in CI (needs network + token).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any

from agent.mcp_client import Toolbox

ROOT = Path(__file__).resolve().parents[2]
CODE_EXT = (".py", ".ts", ".tsx", ".js", ".sql", ".ipynb", ".r")
MAX_FILES_PER_REPO = 8


def _json(result: Any) -> Any:
    """GitHub MCP tools return JSON as text content."""
    text = result if isinstance(result, str) else "".join(
        (c.get("text", "") if isinstance(c, dict) else str(c)) for c in (result if isinstance(result, list) else [result]))
    try:
        return json.loads(text)
    except ValueError:
        return text


async def ingest(owner: str, persona: str, max_repos: int = 5, out_root: Path | None = None) -> list[str]:
    tb = Toolbox.from_config()
    out_root = out_root or ROOT / "data" / "personas" / persona / "repos"
    repos = _json(await tb.call("ingestion", "search_repositories", {"query": f"user:{owner} fork:false", "perPage": max_repos}))
    items = repos.get("items", []) if isinstance(repos, dict) else []
    written = []
    for r in items[:max_repos]:
        name = r["name"]
        rdir = out_root / name
        (rdir / "src").mkdir(parents=True, exist_ok=True)
        fm = {"id": f"{persona}-repo-{name}", "type": "repo", "persona": persona, "project": name,
              "date": (r.get("pushed_at") or "")[:10], "source": r.get("html_url"), "synthetic": False}
        readme = await _file(tb, owner, name, "README.md") or f"# {name}\n\n{r.get('description') or ''}\n"
        (rdir / "README.md").write_text("---\n" + json.dumps(fm) + "\n---\n" + readme, encoding="utf-8")
        tree = _json(await tb.call("ingestion", "get_file_contents", {"owner": owner, "repo": name, "path": "/"}))
        files = [f["path"] for f in (tree if isinstance(tree, list) else []) if f.get("type") == "file"
                 and f["path"].lower().endswith(CODE_EXT + ("requirements.txt", "package.json", "pyproject.toml"))]
        for path in files[:MAX_FILES_PER_REPO]:
            body = await _file(tb, owner, name, path)
            if body:
                safe = re.sub(r"[^\w.\-]", "_", path)
                (rdir / "src" / safe).write_text(body[:20000], encoding="utf-8")
        written.append(name)
    return written


async def _file(tb: Toolbox, owner: str, repo: str, path: str) -> str | None:
    try:
        d = _json(await tb.call("ingestion", "get_file_contents", {"owner": owner, "repo": repo, "path": path}))
    except Exception:  # noqa: BLE001 - missing file
        return None
    if isinstance(d, dict) and d.get("encoding") == "base64":
        return base64.b64decode(d.get("content", "")).decode("utf-8", errors="replace")
    return d if isinstance(d, str) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--persona", required=True)
    ap.add_argument("--max-repos", type=int, default=5)
    a = ap.parse_args()
    print(asyncio.run(ingest(a.owner, a.persona, a.max_repos)))


if __name__ == "__main__":
    main()
