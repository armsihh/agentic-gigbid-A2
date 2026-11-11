import type { RunEvent } from "../lib/hooks";

const LABEL: Record<string, string> = {
  scout: "Scout", analyst: "Job Analyst", risk_assessor: "Risk Assessor", fit_matcher: "Fit Matcher",
  decide: "Bid / skip decision", pricing: "Pricing Strategist", writer: "Proposal Writer", verify: "Claim verification",
  critic: "Critic", compliance: "Compliance Guard", preview: "Dry-run preview", approval: "Your approval",
  submit: "Submit to marketplace", load: "Read messages", intent: "Intent", slots: "Calendar slots",
  client_liaison: "Client Liaison", send: "Send message",
};

/** Node-by-node progress, streamed live from LangGraph. */
export function RunTimeline({ events, status }: { events: RunEvent[]; status: string }) {
  const nodes = events.filter((e) => e.type !== "run" || e.status !== "running");
  return (
    <div>
      <div className="row between">
        <h2>Agent progress</h2>
        <span className={`badge ${status === "failed" ? "bad" : status === "running" ? "info" : "ok"}`} data-testid="run-status">
          {status.replace("_", " ")}
        </span>
      </div>
      {nodes.length === 0 && <p className="muted small">Starting… steps appear here as each agent finishes.</p>}
      <ol className="timeline" aria-live="polite">
        {nodes.map((e) => (
          <li key={e.seq}>
            <span className={`dot ${e.type === "interrupt" ? "wait" : e.status === "failed" ? "bad" : ""}`} />
            <div>
              <strong>{e.type === "run" ? `Run ${e.status}` : LABEL[e.node ?? ""] ?? e.node}</strong>
              {e.latency_ms ? <span className="small muted"> · {Math.round(e.latency_ms)} ms</span> : null}
              {e.model ? <span className="small muted"> · {e.model}</span> : null}
              <div className="small">{e.summary ?? e.error}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
