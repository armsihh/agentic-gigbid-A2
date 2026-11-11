"""Risk Assessor: client quality from history + scam / free-work / off-platform / injection flags.

Deterministic by design (config-driven patterns and weights in agent/config.yaml `risk`): it runs on every job,
so it must be cheap, fast and explainable; every flag carries the quote that triggered it.
"""
from __future__ import annotations

import math
import re
from typing import Any

from agent.guardrails.injection import scan
from agent.handoffs import RiskFlag, RiskReport
from agent.nodes.common import Deps, config, step, tool_json


def client_quality(c: dict[str, Any]) -> float:
    if not c:
        return 0.3
    q = 0.25 + 0.25 * bool(c.get("payment_verified"))
    q += 0.2 * min(1.0, math.log10(1 + float(c.get("total_spent") or 0)) / 5)
    if c.get("rating"):
        q += 0.15 * (float(c["rating"]) / 5)
    if c.get("hire_rate") is not None:
        q += 0.15 * float(c["hire_rate"])
    return round(min(1.0, q), 3)


def assess(job: dict[str, Any], client: dict[str, Any], duplicate_of: str | None = None) -> RiskReport:
    rc = config()["risk"]
    inj = scan(f"{job.get('title', '')}\n{job.get('description', '')}")
    text = inj.sanitized  # scam patterns run on the post WITHOUT injected instructions (flagged separately)
    low = text.lower()
    flags: list[RiskFlag] = []
    for ftype, pats in rc["patterns"].items():
        for p in pats:
            m = re.search(p, low)
            if m:
                quote = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ").strip()
                sev = "high" if rc["weights"][ftype] >= 0.8 else "medium"
                flags.append(RiskFlag(type=ftype if ftype != "crypto_payment" else "off_platform", severity=sev,
                                      evidence=quote))
                break
    if inj.detected:
        flags.append(RiskFlag(type="prompt_injection", severity="high",
                              evidence=(inj.excerpts[0] if inj.excerpts else ", ".join(inj.matches))[:160]))
    if client and not client.get("payment_verified"):
        flags.append(RiskFlag(type="unverified_payment", severity="low", evidence="client payment not verified"))
    if client and not client.get("total_spent") and not client.get("reviews"):
        flags.append(RiskFlag(type="no_history", severity="low", evidence="no spend and no reviews"))
    budget = job.get("budget")
    m = re.search(r"\$\s?([\d,]+)[^.]{0,30}?\b(\d+)\s*hours?\b", low)
    if m and float(m.group(1).replace(",", "")) / max(1, int(m.group(2))) > rc["budget_unrealistic_usd_per_hour"]:
        flags.append(RiskFlag(type="budget_unrealistic", severity="medium", evidence=m.group(0)))
    if budget == 0 and job.get("payment_type") == "fixed":
        flags.append(RiskFlag(type="free_work", severity="high", evidence="fixed budget of $0"))
    if duplicate_of:
        flags.append(RiskFlag(type="duplicate", severity="low", evidence=f"repost of {duplicate_of}"))

    weight = {"prompt_injection": rc["weights"]["prompt_injection"], "unverified_payment": rc["weights"]["payment_unverified"],
              "duplicate": 0.0}
    prod = 1.0
    for f in flags:
        w = weight.get(f.type, rc["weights"].get(f.type, 0.3))
        prod *= 1 - w
    score = round(1 - prod, 3)
    level = "high" if score >= 0.7 else ("medium" if score >= 0.35 else "low")
    kinds = sorted({f.type for f in flags})
    return RiskReport(score=score, level=level, flags=flags, client_quality=client_quality(client),
                      injection_detected=inj.detected,
                      explanation=(f"Signals: {', '.join(kinds)}." if kinds else "No risk signals found.")
                      + f" Client quality {client_quality(client):.2f}.")


def make_risk_node(deps: Deps):
    async def risk_assessor(state: dict) -> dict:
        job = state["job"]
        client = state.get("client") or {}
        if not client and job.get("client_id"):
            client = tool_json(await deps.toolbox.call("risk_assessor", "get_client_history",
                                                      {"client_id": job["client_id"]}))
        rep = assess(job, client if isinstance(client, dict) else {}, job.get("duplicate_of"))
        return {"risk_report": rep.model_dump(), "client": client,
                "trace": [step("risk_assessor", f"risk {rep.score} ({rep.level}): {rep.explanation}")]}
    return risk_assessor
