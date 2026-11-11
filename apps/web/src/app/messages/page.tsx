import { useState } from "react";
import { api, must } from "../../lib/api/client";
import { useLoad, useRunStream } from "../../lib/hooks";
import { ApprovalPanel } from "../../components/ApprovalPanel";
import { RunTimeline } from "../../components/RunTimeline";
import { Empty, ErrorState, Loading } from "../../components/ui";

type Thread = { thread_id: string; job_title?: string; messages: { message_id: string; sender: string; text: string; at?: string }[];
  intent?: string; pending_approval?: boolean; graph_thread_id: string };

/** Client threads with a suggested reply and interview slots; nothing is sent before approval. */
export default function MessagesPage() {
  const list = useLoad<{ threads: Thread[] }>(async () => (await must(api.GET("/api/messages/threads"))) as { threads: Thread[] }, [], 10000);
  const [open, setOpen] = useState<string>();
  const [runId, setRunId] = useState<string>();
  const detail = useLoad<any>(async () => (open ? must(api.GET("/api/messages/threads/{thread_id}", { params: { path: { thread_id: open } } })) : undefined), [open, runId], 5000);
  const run = useRunStream(runId);

  async function suggest() {
    if (!open) return;
    const r = await must(api.POST("/api/messages/threads/{thread_id}/suggest", { params: { path: { thread_id: open } } }));
    setRunId(r.run_id);
  }
  const d = detail.data;
  return (
    <>
      <h1>Messages</h1>
      <p className="sub">Client replies with suggested responses. Client messages are untrusted; GigBid never moves you off-platform.</p>
      <div className="grid two">
        <div className="card">
          {list.error && <ErrorState error={list.error} retry={list.reload} />}
          {list.loading && <Loading />}
          {list.data && list.data.threads.length === 0 && <Empty>No client conversations yet. They appear when a client replies to a proposal.</Empty>}
          {list.data?.threads.map((t) => (
            <button key={t.thread_id} className="btn" style={{ width: "100%", textAlign: "left", marginBottom: 6,
              background: open === t.thread_id ? "var(--surface-2)" : undefined }} onClick={() => { setOpen(t.thread_id); setRunId(undefined); }}>
              <div className="row between"><strong>{t.job_title?.slice(0, 60) ?? t.thread_id}</strong>
                {t.pending_approval && <span className="badge info">reply ready</span>}
                {t.intent === "scam_signal" && <span className="badge bad">scam signal</span>}</div>
              <div className="small muted">{t.messages.at(-1)?.text.slice(0, 90)}</div>
            </button>
          ))}
        </div>
        <div className="stack">
          {!open && <div className="card"><Empty>Pick a conversation.</Empty></div>}
          {open && d && (
            <>
              <div className="card stack">
                <h2>{d.thread.job_title}</h2>
                {d.thread.messages.map((m: any) => <div key={m.message_id} className={`msg ${m.sender}`}>{m.text}</div>)}
                {!d.pending_approval && <button className="btn primary" onClick={suggest}>Suggest a reply</button>}
              </div>
              {runId && <div className="card"><RunTimeline events={run.events} status={run.status} /></div>}
              {d.pending_approval && d.reply_draft && (
                <>
                  <div className="card"><h2>Suggested reply <span className="badge">{d.intent}</span></h2>
                    <div className="letter">{d.reply_draft.text}</div>
                    {d.slots?.length > 0 && <p className="small muted">Free slots offered: {d.slots.map((s: any) => s.start.slice(0, 16).replace("T", " ")).join(", ")} ({d.slots[0].timezone})</p>}
                  </div>
                  <ApprovalPanel threadId={d.graph_thread_id} original={d.reply_draft.text} label="message"
                    preview={null} onDecided={(r) => setRunId(r)} />
                </>
              )}
              {d.status === "blocked" && <div className="banner bad">The suggested reply was blocked by compliance: {d.compliance?.blocked_reason}</div>}
            </>
          )}
        </div>
      </div>
    </>
  );
}
