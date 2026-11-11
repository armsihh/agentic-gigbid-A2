"""Scout: run saved searches, deduplicate, queue new jobs (one bid-graph thread per job).

Deduplication is two-level: exact job id (already seen), and near-duplicate reposts (same client, or same
normalised title + description prefix). Runs on the worker's schedule, never inside a web request."""
from __future__ import annotations

import hashlib
import re

from agent.nodes.common import Deps, step, tool_json


def fingerprint(job: dict) -> str:
    title = re.sub(r"^(urgent|new|\(reposted\))\W*", "", job["title"].lower().strip())
    title = re.sub(r"\W+", "", title)
    desc = re.sub(r"\W+", "", (job.get("description") or job.get("snippet") or "").lower())[:200]
    return hashlib.sha1(f"{title}|{desc}".encode()).hexdigest()[:16]


async def scout(deps: Deps, saved_search: dict, seen_ids: set[str], seen_fps: dict[str, str]) -> list[dict]:
    """Returns new jobs (full posts) with `duplicate_of` set for reposts. Caller persists seen sets."""
    page = tool_json(await deps.toolbox.call("scout", "search_jobs", {k: v for k, v in saved_search.items() if v}))
    new = []
    for summary in (page.get("items", []) if isinstance(page, dict) else []):
        if summary["job_id"] in seen_ids:
            continue
        job = tool_json(await deps.toolbox.call("scout", "get_job", {"job_id": summary["job_id"]}))
        fp = fingerprint(job)
        job["duplicate_of"] = seen_fps.get(fp)
        seen_fps.setdefault(fp, job["job_id"])
        seen_ids.add(job["job_id"])
        new.append(job)
    return new


def make_ingest_node(deps: Deps):
    """First node of the bid graph: load the full job if only an id was handed in."""
    async def ingest(state: dict) -> dict:
        job = state["job"]
        if "description" not in job:
            job = tool_json(await deps.toolbox.call("scout", "get_job", {"job_id": job["job_id"]})) | {
                "duplicate_of": job.get("duplicate_of")}
        return {"job": job, "status": "running", "trace": [step("scout", f"job {job['job_id']}: {job['title'][:80]}")]}
    return ingest
