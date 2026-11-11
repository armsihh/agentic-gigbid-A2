"""Proposal studio: draft with evidence behind every claim, critic and compliance notes, dry-run preview,
regenerate one paragraph."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.guardrails.injection import scan, wrap_untrusted
from agent.nodes.common import structured
from agent.nodes.compliance import check as compliance_check
from agent.prompts import load_prompt
from apps.api.auth.users import CurrentUser
from apps.api.db import User
from apps.api.runs import bid_thread
from apps.api.runtime import runtime
from apps.api.schemas import ParagraphIn, Studio

router = APIRouter(tags=["proposals"])


async def _snap(user: User, job_id: str):
    g = runtime.graph(user, "bid")
    cfg = {"configurable": {"thread_id": bid_thread(user.id, job_id)}}
    snap = await g.aget_state(cfg)
    if not (snap.values or {}).get("draft"):
        raise HTTPException(404, "no draft for this job yet")
    return g, cfg, snap


@router.get("/proposals/{job_id}", response_model=Studio)
async def studio(job_id: str, user: User = CurrentUser):
    _, _, snap = await _snap(user, job_id)
    v = snap.values
    ev = {e["evidence_id"]: e for e in v.get("evidence") or []}
    claims = [{"text": c["text"], "evidence": [ev[i] for i in c.get("evidence_ids", []) if i in ev]}
              for c in v["draft"].get("claims", [])]
    return Studio(thread_id=bid_thread(user.id, job_id), job=v["job"], draft=v["draft"], claims=claims,
                  verification=v.get("verification"), critiques=v.get("critiques") or [], compliance=v.get("compliance"),
                  price=v.get("price"), risk_report=v.get("risk_report"), dry_run_preview=v.get("dry_run_preview"),
                  pending_approval=bool(snap.tasks and any(t.interrupts for t in snap.tasks)), status=v.get("status"))


class ParagraphOut(BaseModel):
    cover_letter: str
    compliance: dict


class _Para(BaseModel):
    paragraph: str


@router.post("/proposals/{job_id}/regenerate-paragraph", response_model=ParagraphOut)
async def regenerate_paragraph(job_id: str, body: ParagraphIn, user: User = CurrentUser):
    """Rewrite ONE paragraph with the writer model, grounded in the same evidence. Returns a suggestion only:
    the human applies it through the normal edit -> approval path (which re-runs compliance)."""
    _, _, snap = await _snap(user, job_id)
    v = snap.values
    paras = [p for p in v["draft"]["cover_letter"].split("\n\n") if p.strip()]
    if body.index >= len(paras):
        raise HTTPException(400, f"draft has {len(paras)} paragraphs")
    from agent.nodes.writer import render_evidence
    deps = runtime.deps(user)
    user_msg = (f"Rewrite ONLY this paragraph. Instruction: {body.instruction}\n\nPARAGRAPH:\n{paras[body.index]}\n\n"
                f"FULL DRAFT (context):\n{v['draft']['cover_letter']}\n\n"
                f"{wrap_untrusted('job_post', scan(v['job']['description']).sanitized[:2000])}\n\n"
                f"EVIDENCE (only facts you may claim):\n{render_evidence(v.get('evidence') or [])}")
    out, _ = await structured(deps, "writer", _Para, load_prompt("paragraph").render(), user_msg)
    paras[body.index] = out.paragraph.strip()
    letter = "\n\n".join(paras)
    return ParagraphOut(cover_letter=letter, compliance=compliance_check(letter, deps.profile).model_dump())
