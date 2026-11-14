# GigBid Portfolio MCP server

Give any MCP host (Claude Desktop, Claude Code, Cursor, ...) read-only, evidence-grade access to a freelancer's
portfolio: case studies, repositories (README **and code**), CV, client reviews and past proposals with their outcomes.
Built with the official MCP Python SDK. Part of [GigBid](../../README.md).

## Install and run
No clone needed (requires [uv](https://docs.astral.sh/uv/)):
```bash
PORTFOLIO_DIR=/path/to/my-portfolio uvx --from git+https://github.com/armsihh/agentic-gigbid-A2 gigbid-portfolio-mcp
```
First run downloads two small CPU models (~200 MB, cached): BAAI/bge-small-en-v1.5 embeddings and the
ms-marco-MiniLM-L-6 cross-encoder.

**Claude Desktop / Cursor** (`claude_desktop_config.json` or `.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "portfolio": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/armsihh/agentic-gigbid-A2", "gigbid-portfolio-mcp"],
      "env": {"PORTFOLIO_DIR": "/path/to/my-portfolio", "PORTFOLIO_PERSONA": "me"}
    }
  }
}
```
**Claude Code:** `claude mcp add portfolio -e PORTFOLIO_DIR=/path/to/my-portfolio -- uvx --from git+https://github.com/armsihh/agentic-gigbid-A2 gigbid-portfolio-mcp`

**Over HTTP with bearer auth:** add `--http --port 8102` and set `PORTFOLIO_MCP_TOKENS="token:user:portfolio:read"`.

Try it on the demo personas: clone the repo and set `PORTFOLIO_DIR=<repo>/data/personas`, `PORTFOLIO_PERSONA=ai_ml`.

## Portfolio folder layout
```
my-portfolio/
  me/                                  # one folder per freelancer (PORTFOLIO_PERSONA picks one)
    profile.json                       # {"name", "headline", "hourly_rate", "skills": [...]}
    cv.md                              # one "- " bullet per project
    case_studies/<id>.md               # JSON front-matter {"id","project","skills","date","client_industry"} + markdown
    repos/<name>/README.md             # front-matter {"id","project"} + README; code files under repos/<name>/src/
    reviews.jsonl                      # {"id","project","text","rating","date"}
    past_proposals.jsonl               # {"id","project","job_title","text","outcome": "won|replied|ignored","date"}
```
Add or edit files at any time: the index refreshes incrementally on the next call.

## What it exposes
**Tools** (all read-only, with input/output schemas):
- `search_evidence(requirement, k, types?, outcome?, project?, since?)`: evidence items with type, source, date
  and outcome for ONE requirement. Call it once per requirement.
- `get_case_study(id)`: a full case study plus the ids of related items about the same project.
- `list_skills()`: skills with how many case studies prove each.

**Resources:** `portfolio://profile`, `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://repo/{id}`.

**Prompts:** "Answer a screening question from my portfolio", "Write a cover letter opening for a job",
"Do I have experience with X?".

## How retrieval works
Hybrid BM25 + dense embeddings fused with reciprocal rank fusion, a cross-encoder rerank, and results grouped per
project. It was chosen by measurement on 460 labelled jobs: best Recall@5 (0.648) and nDCG@10 (0.697) of 7 variants
(`evals/results/rag_retrieval_dev.json`). Set `RAG_VARIANT=v2_hybrid` on small machines (no cross-encoder).
Code is indexed separately from READMEs, so skills that only appear in imports (e.g. Celery) are still found.
