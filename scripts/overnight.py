"""Overnight LLM evaluation queue (Groq free tier: 200k tokens/day/model, rolling window).

Waits until the needed model accepts a request, then runs each job in order; every runner saves partial results and
waits out 429s itself. Log: data/runtime/overnight.log

    uv run python -m scripts.overnight
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "runtime" / "overnight.log"
KEY = dotenv_values(ROOT / ".env").get("GROQ_API_KEY", "")

JOBS = [  # (name, model that must have quota, command, extra env)
    ("judge_calibration", "openai/gpt-oss-20b",
     [sys.executable, "-u", "-m", "evals.runners.judge_calibration"], {}),
    ("proposal_eval V0 vs V5", "qwen/qwen3.8-27b",
     [sys.executable, "-u", "-m", "evals.runners.proposal_eval", "--per-persona", "2"], {"MODEL_PROFILE": "open_eval"}),
]


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def has_quota(model: str) -> bool:
    try:
        r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}, timeout=30)
        return r.status_code == 200 and int(r.headers.get("x-ratelimit-remaining-tokens", "0")) > 4000
    except httpx.HTTPError:
        return False


def main() -> None:
    for name, model, cmd, env in JOBS:
        while not has_quota(model):
            log(f"waiting for quota on {model} before: {name}")
            time.sleep(600)
        log(f"START {name}")
        p = subprocess.run(cmd, check=False, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8", "LLM_MAX_RETRIES": "6", **env},
                           stdout=(LOG.parent / f"{name.split()[0]}.log").open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        log(f"END {name}: exit {p.returncode}")
    log("ALL DONE")


if __name__ == "__main__":
    main()
