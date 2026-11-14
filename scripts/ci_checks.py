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


GIGSIM_MANIFEST = ROOT / "gigsim" / "MANIFEST.sha256"


def _gigsim_hashes() -> dict[str, str]:
    import hashlib
    files = sorted(f for f in (ROOT / "gigsim").rglob("*") if f.is_file() and f.name != "MANIFEST.sha256"
                   and "__pycache__" not in f.parts)
    crlf, lf = bytes([13, 10]), bytes([10])  # normalise line endings so Windows and Linux checkouts agree
    return {f.relative_to(ROOT).as_posix(): hashlib.sha256(f.read_bytes().replace(crlf, lf)).hexdigest()
            for f in files}


def check_gigsim() -> int:
    """The simulator is frozen (the assignment treats gigsim/ as provided): any change must be deliberate,
    by regenerating the manifest with `python -m scripts.ci_checks freeze-gigsim`."""
    want = dict(line.split("  ", 1)[::-1] for line in GIGSIM_MANIFEST.read_text().splitlines() if line.strip())
    got = _gigsim_hashes()
    diff = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
    if diff:
        print("gigsim/ changed (frozen simulator):", *diff, sep="\n  ")
        return 1
    print("gigsim: unchanged")
    return 0


def freeze_gigsim() -> int:
    GIGSIM_MANIFEST.write_text("".join(f"{h}  {f}\n" for f, h in _gigsim_hashes().items()))
    print(f"wrote {GIGSIM_MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit({"prompts": check_prompts, "gigsim": check_gigsim, "freeze-gigsim": freeze_gigsim}[sys.argv[1]]())
