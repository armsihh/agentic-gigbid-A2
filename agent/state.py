"""Typed graph state (C2).

Three things are kept apart:
  * State (this file): what one job / conversation needs right now. Checkpointed by the Postgres saver.
  * Execution trace: every tool name, argument, result and observation -> the `trace` channel here is only an
    index of step summaries; full payloads live in LangSmith/Langfuse traces and the MCP audit logs (trace_id).
  * Long-term memory: promoted knowledge only, in the LangGraph store (agent/memory), never written from here.

Parallel branches (Job Analyst, Risk Assessor, Fit Matcher) each write their OWN field, so they never collide;
list-valued channels written by several nodes use append reducers.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

ThreadStatus = Literal["running", "waiting_approval", "approved", "submitted", "skipped", "watching",
                       "blocked", "needs_attention", "queued_marketplace_down", "dead_letter", "rejected"]


def keep_last(_old: Any, new: Any) -> Any:
    return new


HALT_SEVERITY = {None: 0, "needs_attention": 1, "queued_marketplace_down": 2, "dead_letter": 3}


def merge_halt(old: str | None, new: str | None) -> str | None:
    """Parallel branches may fail in the same step: keep the most severe halt reason."""
    return new if HALT_SEVERITY.get(new, 0) >= HALT_SEVERITY.get(old, 0) else old


class TraceStep(TypedDict, total=False):
    node: str
    at: str
    summary: str
    tokens: int
    cost_usd: float
    latency_ms: float


class BidState(TypedDict, total=False):
    # identity
    thread_id: str
    user_id: str
    persona: str
    trace_id: str
    # the job (raw post is UNTRUSTED text)
    job: dict[str, Any]
    client: dict[str, Any]
    # parallel analyses, one field per branch
    job_spec: dict[str, Any]          # JobSpec
    risk_report: dict[str, Any]       # RiskReport
    fit_report: dict[str, Any]        # FitReport
    evidence: Annotated[list[dict[str, Any]], operator.add]   # evidence items seen (id, text, source)
    # decision + price
    decision: dict[str, Any]          # BidDecision
    price: dict[str, Any]             # PriceQuote
    # drafting loop
    draft: dict[str, Any]             # ProposalDraft (current)
    verification: dict[str, Any]      # VerificationReport of the current draft
    critiques: Annotated[list[dict[str, Any]], operator.add]  # every Critique, in order
    revisions: int
    compliance: dict[str, Any]        # ComplianceVerdict
    # human in the loop + outcome
    approval: dict[str, Any]          # ApprovalDecision
    dry_run_preview: dict[str, Any]
    submission: dict[str, Any]        # marketplace result after approval
    outcome: dict[str, Any]           # later: viewed / replied / hired / lost
    # control
    status: ThreadStatus                          # written only by sequential nodes
    halt: Annotated[str | None, merge_halt]       # set by any node (incl. parallel) to stop the thread
    steps: Annotated[int, operator.add]          # every node adds 1 (parallel-safe)
    tokens_used: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceStep], operator.add]


class ConversationState(TypedDict, total=False):
    thread_id: str
    user_id: str
    persona: str
    trace_id: str
    marketplace_thread_id: str
    proposal: dict[str, Any]
    messages: list[dict[str, Any]]    # client messages are UNTRUSTED
    last_seen_message_id: str | None
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"] | None
    reply_draft: dict[str, Any]
    slots: list[dict[str, Any]]
    compliance: dict[str, Any]
    approval: dict[str, Any]
    sent: dict[str, Any]
    status: ThreadStatus
    halt: Annotated[str | None, merge_halt]
    steps: Annotated[int, operator.add]          # every node adds 1 (parallel-safe)
    tokens_used: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[TraceStep], operator.add]
