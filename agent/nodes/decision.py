"""Bid / watch / skip decision. Rules from agent/config.yaml `decision`, every reason recorded (explainable,
and the change request is absorbed by editing config, not code)."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes.common import config, step


def decide(job: dict, risk: dict, fit: dict, profile: dict, autonomy: dict | None = None) -> BidDecision:
    d = config()["decision"]
    reasons: list[str] = []
    skip = False
    if risk.get("score", 0) >= d["skip_if_risk_at_least"]:
        skip = True
        reasons.append(f"risk {risk['score']:.2f} >= {d['skip_if_risk_at_least']}: "
                       + ", ".join(sorted({f['type'] for f in risk.get('flags', []) if f['severity'] != 'low'})))
    if d["skip_if_injection"] and risk.get("injection_detected"):
        skip = True
        reasons.append("post contains instructions aimed at AI tools (prompt injection)")
    if d["skip_if_duplicate"] and job.get("duplicate_of"):
        skip = True
        reasons.append(f"duplicate of {job['duplicate_of']}")
    fit_score = fit.get("score", 0)
    if fit_score < d["skip_if_fit_below"]:
        skip = True
        missing = ", ".join(fit.get("missing_skills", [])[:4])
        reasons.append(f"fit {fit_score:.2f} < {d['skip_if_fit_below']}" + (f" (missing: {missing})" if missing else ""))
    if not fit.get("evidence_ids"):
        skip = True
        reasons.append("no portfolio evidence for the requirements")
    rate, floor = profile.get("hourly_rate"), profile.get("min_fixed_budget")
    if job.get("payment_type") == "hourly" and rate and job.get("hourly_high") and \
            job["hourly_high"] < d["hourly_min_ratio_of_rate"] * rate:
        skip = True
        reasons.append(f"hourly max ${job['hourly_high']:.0f} < {d['hourly_min_ratio_of_rate']:.0%} of rate ${rate}")
    if job.get("payment_type") == "fixed" and d["use_profile_min_fixed_budget"] and floor and job.get("budget") \
            and job["budget"] < floor:
        skip = True
        reasons.append(f"budget ${job['budget']:.0f} below minimum ${floor}")
    if skip:
        return BidDecision(action="skip", reasons=reasons, confidence=0.9, decided_by="rules")
    if fit_score < d["watch_if_fit_below"]:
        return BidDecision(action="watch", reasons=[f"fit {fit_score:.2f} is borderline (< {d['watch_if_fit_below']})"],
                           confidence=0.6, decided_by="rules")
    return BidDecision(action="bid", reasons=[f"fit {fit_score:.2f}, risk {risk.get('score', 0):.2f}",
                                              *fit.get("reasons", [])[:2]], confidence=0.75, decided_by="rules")


def make_decision_node(deps):
    async def decide_node(state: dict) -> dict:
        dec = decide(state["job"], state.get("risk_report", {}), state.get("fit_report", {}), deps.profile)
        status = {"skip": "skipped", "watch": "watching", "bid": "running"}[dec.action]
        return {"decision": dec.model_dump(), "status": status,
                "trace": [step("decide", f"{dec.action}: {'; '.join(dec.reasons)}")]}
    return decide_node
