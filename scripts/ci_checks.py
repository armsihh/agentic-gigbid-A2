"""Repository rules enforced in CI.

    uv run python -m scripts.ci_checks prompts   # every LLM prompt lives in agent/prompts/*.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_CODE = [ROOT / "agent", ROOT / "rag", ROOT / "apps" / "api"]
# A long triple-quoted string that talks to a model ("You are", "Return JSON") is an inline prompt.
INLINE_PROMPT = re.compile(r'(?s)("""|\'\'\')\s*(You are|You will|Return (only )?(valid )?JSON|Respond with)')


def check_prompts() -> int:
    bad = []
    for base in AGENT_CODE:
        for f in base.rglob("*.py"):
            if INLINE_PROMPT.search(f.read_text(encoding="utf-8")):
                bad.append(f.relative_to(ROOT).as_posix())
    if bad:
        print("Inline prompts found (move them to agent/prompts/<node>.md):\n  " + "\n  ".join(bad))
        return 1
    print("prompts: ok")
    return 0


if __name__ == "__main__":
    sys.exit({"prompts": check_prompts}[sys.argv[1]]())
