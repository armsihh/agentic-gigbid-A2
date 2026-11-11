import { useState } from "react";
import { api, must } from "../lib/api/client";

type Props = {
  threadId: string;
  original: string;
  preview?: Record<string, unknown> | null;
  onDecided: (runId: string) => void;
  label?: string;
};

/** Approve / edit / reject. Nothing is sent until the human acts here; the decision resumes the paused graph. */
export function ApprovalPanel({ threadId, original, preview, onDecided, label = "proposal" }: Props) {
  const [mode, setMode] = useState<"view" | "edit" | "reject">("view");
  const [text, setText] = useState(original);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();

  async function decide(action: "approve" | "edit" | "reject") {
    setBusy(true);
    setErr(undefined);
    try {
      const body =
        action === "edit" ? { action, edited_cover_letter: text } : action === "reject" ? { action, reason } : { action };
      const r = await must(api.POST("/api/approvals/{thread_id}", { params: { path: { thread_id: threadId } }, body }));
      onDecided(r.run_id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const cost = preview?.connects_cost as number | undefined;
  const after = preview?.connects_balance_after as number | undefined;
  return (
    <div className="card stack" data-testid="approval-panel">
      <h2>Your decision</h2>
      {cost !== undefined && (
        <div className="banner info small" data-testid="dry-run">
          <strong>Dry run:</strong> sending this {label} costs <strong>{cost} Connects</strong>
          {after !== undefined && <> (balance after: {after})</>}. Nothing has been sent yet.
        </div>
      )}
      {mode === "edit" && (
        <label>
          Edit the {label} (your changes are re-checked by Compliance and teach GigBid your style)
          <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Edited text" />
        </label>
      )}
      {mode === "reject" && (
        <label>
          Why are you rejecting it? (used in Analytics)
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. scope too large" aria-label="Rejection reason" />
        </label>
      )}
      {err && <div className="banner bad" role="alert">{err}</div>}
      <div className="row">
        {mode === "view" && (
          <>
            <button className="btn primary" disabled={busy} onClick={() => decide("approve")}>Approve and send</button>
            <button className="btn" disabled={busy} onClick={() => setMode("edit")}>Edit</button>
            <button className="btn danger" disabled={busy} onClick={() => setMode("reject")}>Reject</button>
          </>
        )}
        {mode === "edit" && (
          <>
            <button className="btn primary" disabled={busy || !text.trim()} onClick={() => decide("edit")}>Save edit and send</button>
            <button className="btn" onClick={() => { setMode("view"); setText(original); }}>Cancel</button>
          </>
        )}
        {mode === "reject" && (
          <>
            <button className="btn danger" disabled={busy || !reason.trim()} onClick={() => decide("reject")}>Reject with reason</button>
            <button className="btn" onClick={() => setMode("view")}>Cancel</button>
          </>
        )}
      </div>
    </div>
  );
}
