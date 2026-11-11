"""Pricing Strategist: bid from market statistics, client spend and the freelancer's floor; decide whether the
Connects cost is worth it (expected value). Deterministic and config-driven (`pricing` in agent/config.yaml)."""
from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.nodes.common import Deps, config, step, tool_json


def p_win(fit: float, applicants: str | None) -> float:
    c = config()["pricing"]["p_win"]
    pen = c["competition_penalty"].get(applicants or "", 0.03)
    return max(0.01, min(0.6, c["base"] + c["per_fit_point"] * fit - pen))


def quote(job: dict, client: dict, stats: dict, profile: dict, fit: float, connects_cost: int,
          policy_extra_connects: int = 0) -> PriceQuote:
    pc = config()["pricing"]
    rate = float(profile.get("hourly_rate") or 30)
    floor = float(profile.get("min_fixed_budget") or 100)
    total_connects = connects_cost + policy_extra_connects
    connects_usd = total_connects * pc["usd_per_connect"]
    spend_factor = 1.05 if (client.get("total_spent") or 0) > 10_000 else 1.0
    if job.get("payment_type") == "hourly":
        lo, hi = job.get("hourly_low"), job.get("hourly_high")
        mkt = (stats or {}).get("hourly_high") or {}
        target = rate * spend_factor
        if hi:
            target = min(max(target, lo or 0), hi * 1.1)  # stay near the client's range
        amount = round(max(target, rate * 0.85), 2)
        band = (round(max(rate * 0.85, lo or 0), 2), round(max(rate * 1.15, hi or 0), 2))
        rationale = (f"Hourly: your rate ${rate:.0f}; client range {lo or '?'}-{hi or '?'}; market p50 "
                     f"${mkt.get('p50', '?')}/h. Bid ${amount}/h.")
        value_proxy = amount * 20  # ~20h engagement for EV purposes
    else:
        budget = job.get("budget")
        mkt = (stats or {}).get("fixed_budget") or {}
        if budget:
            amount = max(floor, round(budget * 0.95 * spend_factor, -1) or budget)
            amount = min(amount, budget * 1.1)
            band = (round(max(floor, 0.75 * budget), 2), round(max(floor, budget), 2))
            rationale = f"Fixed: client budget ${budget:.0f}; floor ${floor:.0f}; bid ~95% of budget = ${amount:.0f}."
        else:
            p25, p75 = mkt.get("p25", floor), mkt.get("p75", floor * 3)
            amount = max(floor, round((p25 + p75) / 2, -1))
            band = (round(max(floor, p25), 2), round(max(floor, p75), 2))
            rationale = f"Fixed, no budget given: market p25-p75 ${p25:.0f}-${p75:.0f}; bid midpoint ${amount:.0f}."
        value_proxy = amount
    pw = p_win(fit, job.get("applicants"))
    ev = pw * value_proxy - connects_usd
    worth = ev >= pc["min_expected_value_usd"]
    rationale += (f" Connects: {total_connects} (${connects_usd:.2f}); P(win)~{pw:.0%}; expected value ${ev:.0f} -> "
                  + ("worth it." if worth else "NOT worth the Connects."))
    return PriceQuote(amount=float(amount), type=job.get("payment_type", "fixed"), band_low=band[0], band_high=band[1],
                      rationale=rationale, connects_cost=total_connects, connects_worth_it=worth,
                      expected_value_usd=round(ev, 2))


def make_pricing_node(deps: Deps):
    async def pricing(state: dict) -> dict:
        job = state["job"]
        stats = tool_json(await deps.toolbox.call("pricing", "get_market_stats", {"category": job.get("category") or "other"}))
        policy = tool_json(await deps.toolbox.call("pricing", "get_policy", {}))
        extra = int(((policy.get("raw") or policy).get("connects") or {}).get("bid_surcharge", 0) or 0)
        q = quote(job, state.get("client") or {}, stats, deps.profile, state.get("fit_report", {}).get("score", 0),
                  int(job.get("connects_cost") or 0), extra)
        out = {"price": q.model_dump(), "trace": [step("pricing", q.rationale)]}
        if not q.connects_worth_it:
            out["decision"] = {**state.get("decision", {}), "action": "watch",
                               "reasons": [*state.get("decision", {}).get("reasons", []), "Connects cost not worth it"]}
            out["status"] = "watching"
        return out
    return pricing
