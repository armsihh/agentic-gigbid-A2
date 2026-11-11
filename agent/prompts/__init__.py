"""Load versioned prompt files (agent/prompts/<node>.md). No prompt text lives in Python source."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    node: str
    version: int
    text: str

    def render(self, **kw: str) -> str:
        out = self.text
        for k, v in kw.items():
            out = out.replace("{" + k + "}", v or "")
        out = re.sub(r"\{[a-z_]+\}", "", out)
        return re.sub(r"\n{3,}", "\n\n", out).strip()


@lru_cache(maxsize=32)
def load_prompt(node: str) -> Prompt:
    raw = (HERE / f"{node}.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.DOTALL)
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines()) if m else {}
    return Prompt(node=node, version=int(meta.get("version", 1)), text=(m.group(2) if m else raw).strip())
