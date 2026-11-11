"""Fit Matcher: map every requirement to portfolio evidence (via the Portfolio MCP server) and score fit.

Runs in parallel with the Job Analyst, so it derives requirements from the post's skill tags itself
(rag.pipeline.default_requirements). Coverage is judged ONLY from the retrieved evidence text: a requirement is
covered when its key term appears in a retrieved item, partial when related evidence was retrieved, missing otherwise.
"""
from __future__ import annotations

import asyncio
import re

from agent.handoffs import FitReport, RequirementMatch
from agent.nodes.common import Deps, step, tool_json
from rag.pipeline import GENERIC_TAGS

SYN = {"machine learning model": "machine learning", "python scikit-learn": "scikit-learn", "chatbot development": "chatbot",
       "ai chatbot": "chatbot", "artificial neural network": "neural network", "microsoft power bi": "power bi",
       "restful api": "api", "api integration": "api", "api development": "api", "web application": "web app",
       "amazon web services": "aws", "microsoft excel": "excel", "google sheets": "sheets"}


def key_terms(skill: str) -> list[str]:
    s = SYN.get(skill.lower(), skill.lower())
    terms = {s}
    if " " in s:
        terms |= {w for w in s.split() if len(w) > 3}
    return sorted(terms, key=len, reverse=True)


def judge(skill: str, items: list[dict]) -> tuple[str, list[str]]:
    blob = [(i["evidence_id"], (i.get("text", "") + " " + " ".join(i.get("skills", []))).lower()) for i in items]
    terms = key_terms(skill)
    full = [eid for eid, t in blob if re.search(r"(?<![a-z])" + re.escape(terms[0]) + r"(?![a-z])", t)]
    if full:
        return "covered", full[:3]
    part = [eid for eid, t in blob if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t) for w in terms[1:])]
    return ("partial", part[:3]) if part else ("missing", [])


def make_fit_node(deps: Deps):
    async def fit_matcher(state: dict) -> dict:
        job = state["job"]
        skills = [s for s in (job.get("skills") or []) if s.lower() not in GENERIC_TAGS][:8]
        if not skills:
            skills = [job["title"][:60]]

        async def one(skill: str):
            res = tool_json(await deps.toolbox.call("fit_matcher", "search_evidence",
                                                    {"requirement": f"{skill} - {job['title'][:80]}", "k": 4}))
            return skill, res.get("items", []) if isinstance(res, dict) else []

        results = await asyncio.gather(*(one(s) for s in skills))
        matches, evidence, seen = [], [], set()
        for skill, items in results:
            status, ids = judge(skill, items)
            matches.append(RequirementMatch(requirement=skill, status=status, evidence_ids=ids,
                                            note=f"{len(items)} items retrieved"))
            for it in items:
                if it["evidence_id"] in ids and it["evidence_id"] not in seen:
                    seen.add(it["evidence_id"])
                    evidence.append({k: it.get(k) for k in ("evidence_id", "item_id", "type", "source", "title", "text",
                                                            "date", "outcome", "project")})
        n = len(matches)
        score = round(sum(1.0 if m.status == "covered" else 0.5 if m.status == "partial" else 0 for m in matches) / n, 3)
        rep = FitReport(score=score, matches=matches,
                        matched_skills=[m.requirement for m in matches if m.status == "covered"],
                        missing_skills=[m.requirement for m in matches if m.status == "missing"],
                        evidence_ids=sorted(seen),
                        reasons=[f"{sum(m.status == 'covered' for m in matches)}/{n} requirements covered by evidence"])
        return {"fit_report": rep.model_dump(), "evidence": evidence,
                "trace": [step("fit_matcher", f"fit {score}: {rep.reasons[0]}")]}
    return fit_matcher
