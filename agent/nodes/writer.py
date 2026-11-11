"""Proposal Writer (strong model): cover letter + screening answers, every claim citing evidence ids.
Fetches extra evidence for screening questions through the Portfolio MCP server; reads style rules and outcome
insights from long-term memory (promoted items only)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agent.guardrails.injection import scan, wrap_untrusted
from agent.handoffs import Claim, ProposalDraft, ScreeningAnswer
from agent.nodes.common import Deps, step, structured, tool_json
from agent.prompts import load_prompt


class WriterOutput(BaseModel):
    cover_letter: str = Field(description="120-220 words")
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list, description="Each experience claim + the evidence ids behind it")


def render_evidence(items: list[dict], limit: int = 12) -> str:
    lines = []
    for e in items[:limit]:
        meta = ", ".join(x for x in (e.get("type"), e.get("date"), e.get("outcome")) if x)
        lines.append(f"[{e['evidence_id']}] ({meta}) {e.get('title', '')}\n{(e.get('text') or '')[:700]}")
    return "\n\n".join(lines) or "(no evidence found: do not claim relevant experience)"


def make_writer_node(deps: Deps):
    async def writer(state: dict) -> dict:
        job, spec = state["job"], state.get("job_spec") or {}
        evidence = list(state.get("evidence") or [])
        seen = {e["evidence_id"] for e in evidence}
        new_ev = []
        for q in (spec.get("screening_questions") or [])[:3]:
            res = tool_json(await deps.toolbox.call("writer", "search_evidence", {"requirement": q["question"], "k": 3}))
            for it in (res.get("items", []) if isinstance(res, dict) else []):
                if it["evidence_id"] not in seen:
                    seen.add(it["evidence_id"])
                    new_ev.append({k: it.get(k) for k in ("evidence_id", "item_id", "type", "source", "title", "text",
                                                          "date", "outcome", "project")})
        evidence += new_ev
        user_id = state.get("user_id", "local")
        style = deps.memory.style_rules(user_id) if deps.memory else []
        insights = deps.memory.outcome_insights(user_id, job.get("category")) if deps.memory else []
        crit = (state.get("critiques") or [])[-1:] if state.get("revisions") else []
        system = load_prompt("writer").render(
            style_rules=("Style rules learned from this freelancer's edits:\n" + "\n".join(f"- {r['rule']}" for r in style))
            if style else "",
            outcome_insights=("What has worked for this freelancer:\n" + "\n".join(f"- {i['insight']}" for i in insights))
            if insights else "",
            revision_instructions=(f"REVISION {state.get('revisions')}: the critic asked for:\n{crit[0]['revision_instructions']}"
                                   f"\nIssues: {'; '.join(crit[0].get('issues', []))}") if crit else "")
        price = state.get("price") or {}
        user = (f"Freelancer: {deps.profile.get('name')} - {deps.profile.get('headline')}\n"
                f"Bid: {price.get('type')} ${price.get('amount')}\n\n"
                f"JobSpec (from the analyst):\nsummary: {spec.get('summary')}\nrequirements: "
                + "; ".join(r["text"] for r in spec.get("requirements", [])) +
                f"\nscreening questions: {[q['question'] for q in spec.get('screening_questions', [])]}\n\n"
                f"{wrap_untrusted('job_post', scan(job['description']).sanitized[:3000])}\n\n"
                f"EVIDENCE (the only facts you may claim):\n{render_evidence(evidence)}")
        out, usage = await structured(deps, "writer", WriterOutput, system, user)
        draft = ProposalDraft(job_id=job["job_id"], cover_letter=out.cover_letter, screening_answers=out.screening_answers,
                              claims=out.claims, version=int(state.get("revisions", 0)) + 1,
                              evidence_ids=sorted({i for c in out.claims for i in c.evidence_ids}))
        return {"draft": draft.model_dump(), "evidence": new_ev, "tokens_used": usage["tokens"],
                "trace": [step("writer", f"draft v{draft.version}: {len(out.cover_letter.split())} words, "
                                         f"{len(out.claims)} claims", **{k: v for k, v in usage.items() if k != "tokens"})]}
    return writer
