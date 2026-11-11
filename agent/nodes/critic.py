"""Claim verification (B3) then Critic (strong model). The Critic sees the CLEANED draft (unsupported claims
already removed) and can send it back to the Writer at most `budgets.max_revisions` times."""
from __future__ import annotations

from agent.guardrails.injection import wrap_untrusted
from agent.handoffs import Critique
from agent.nodes.common import Deps, config, step, structured
from agent.nodes.writer import render_evidence
from agent.prompts import load_prompt
from rag.verify import Evidence


def make_verify_node(deps: Deps):
    async def verify(state: dict) -> dict:
        draft = state["draft"]
        ev = [Evidence(evidence_id=e["evidence_id"], text=f"{e.get('title', '')}\n{e.get('text', '')}")
              for e in state.get("evidence") or []]
        rep = deps.verifier.verify(draft["cover_letter"], ev)
        answers = []
        removed = list(rep.removed)
        for a in draft.get("screening_answers", []):
            r = deps.verifier.verify(a["answer"], ev)
            removed += r.removed
            answers.append({**a, "answer": r.cleaned_draft or a["answer"]})
        checked = len(rep.claims)
        report = rep.model_dump() | {"unsupported_before": len(removed), "claims_checked": checked}
        return {"verification": report,
                "draft": {**draft, "cover_letter": rep.cleaned_draft, "screening_answers": answers,
                          "unverified_original": draft["cover_letter"]},
                "trace": [step("verify", f"{checked} claims checked, {len(removed)} unsupported removed "
                                         f"(rate {rep.unsupported_rate:.0%})")]}
    return verify


def make_critic_node(deps: Deps):
    async def critic(state: dict) -> dict:
        draft, job = state["draft"], state["job"]
        spec = state.get("job_spec") or {}
        user = (f"Requirements: {'; '.join(r['text'] for r in spec.get('requirements', []))}\n"
                f"Screening questions: {[q['question'] for q in spec.get('screening_questions', [])]}\n\n"
                f"{wrap_untrusted('job_post', job['description'][:2500])}\n\n"
                f"DRAFT COVER LETTER:\n{draft['cover_letter']}\n\nSCREENING ANSWERS:\n"
                + "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in draft.get("screening_answers", []))
                + f"\n\nEVIDENCE:\n{render_evidence(state.get('evidence') or [], 10)}")
        crit, usage = await structured(deps, "critic", Critique, load_prompt("critic").render(), user)
        words = len(draft["cover_letter"].split())
        crit.length_ok = 100 <= words <= 250
        crit.approve = crit.approve and crit.length_ok and crit.grounding >= 4 and crit.personalisation >= 4
        crit.revision_number = int(state.get("revisions", 0))
        out = {"critiques": [crit.model_dump()], "tokens_used": usage["tokens"],
               "trace": [step("critic", ("approved" if crit.approve else f"revise: {'; '.join(crit.issues)[:200]}")
                              + f" (grounding {crit.grounding}, personalisation {crit.personalisation}, {words} words)",
                              **{k: v for k, v in usage.items() if k != "tokens"})]}
        if not crit.approve and int(state.get("revisions", 0)) < config()["budgets"]["max_revisions"]:
            out["revisions"] = int(state.get("revisions", 0)) + 1
        return out
    return critic
