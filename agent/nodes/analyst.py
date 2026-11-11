"""Job Analyst: untrusted job post -> structured JobSpec (small model). No tools.
If the model fails after retries, a minimal JobSpec is built from the post's structured fields (degraded, logged)."""
from __future__ import annotations

from agent.guardrails.injection import scan, wrap_untrusted
from agent.handoffs import Budget, JobSpec, Requirement
from agent.nodes.common import Deps, step, structured
from agent.prompts import load_prompt
from rag.pipeline import GENERIC_TAGS


def fallback_spec(job: dict) -> JobSpec:
    skills = [s for s in job.get("skills") or [] if s.lower() not in GENERIC_TAGS]
    ptype = job.get("payment_type", "unknown")
    return JobSpec(job_id=job["job_id"], title=job["title"], summary=job["title"],
                   requirements=[Requirement(text=s, skills=[s]) for s in skills[:8]], required_skills=skills,
                   budget=Budget(type=ptype if ptype in ("fixed", "hourly") else "unknown",
                                 min=job.get("hourly_low") if ptype == "hourly" else job.get("budget"),
                                 max=job.get("hourly_high") if ptype == "hourly" else job.get("budget")),
                   timeline=job.get("duration") or None, category=job.get("category"),
                   experience_level=job.get("experience_level"))


def make_analyst_node(deps: Deps):
    async def analyst(state: dict) -> dict:
        job = state["job"]
        post = scan(job["description"]).sanitized
        user = (f"Title: {job['title']}\nTagged skills: {', '.join(job.get('skills') or [])}\n"
                f"Budget: {job.get('payment_type')} {job.get('budget') or ''} {job.get('hourly_low') or ''}-"
                f"{job.get('hourly_high') or ''}\n\n{wrap_untrusted('job_post', post)}")
        try:
            spec, usage = await structured(deps, "analyst", JobSpec, load_prompt("analyst").render(), user)
            spec.job_id, spec.title = job["job_id"], job["title"]
            note = f"{len(spec.requirements)} requirements, {len(spec.screening_questions)} screening questions"
        except Exception as e:  # noqa: BLE001 - degrade, never block the pipeline on the analyst
            spec, usage = fallback_spec(job), {"tokens": 0}
            note = f"FALLBACK spec from tags ({type(e).__name__})"
        return {"job_spec": spec.model_dump(), "tokens_used": usage.get("tokens", 0),
                "trace": [step("analyst", note, **{k: v for k, v in usage.items() if k != "tokens"})]}
    return analyst
