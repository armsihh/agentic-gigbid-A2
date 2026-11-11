import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, must, type Studio } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { ApprovalPanel } from "../../components/ApprovalPanel";
import { EvidenceHover, type ClaimWithEvidence } from "../../components/EvidenceHover";
import { ErrorState, Loading, money, RiskBadge, StatusBadge } from "../../components/ui";

/** Render the letter with each verified claim underlined; hover shows its evidence. */
function Letter({ text, claims }: { text: string; claims: ClaimWithEvidence[] }) {
  const parts: (string | ClaimWithEvidence)[] = [text];
  for (const c of claims) {
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i];
      if (typeof p !== "string") continue;
      const at = p.indexOf(c.text);
      if (at >= 0) { parts.splice(i, 1, p.slice(0, at), c, p.slice(at + c.text.length)); break; }
    }
  }
  return <div className="letter" data-testid="letter">{parts.map((p, i) => typeof p === "string" ? <span key={i}>{p}</span> : <EvidenceHover key={i} claim={p} />)}</div>;
}

/** Proposal studio: draft with evidence on hover, Critic + Compliance notes, regenerate a paragraph, dry run, approval. */
export default function StudioPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const s = useLoad<Studio>(() => must(api.GET("/api/proposals/{job_id}", { params: { path: { job_id: id } } })), [id]);
  const [para, setPara] = useState<{ text: string; compliance: any } | null>(null);
  const [regenBusy, setRegenBusy] = useState<number | null>(null);
  if (s.error) return <ErrorState error={s.error} retry={s.reload} />;
  if (!s.data) return <Loading lines={10} />;
  const st = s.data;
  const draft = st.draft as Record<string, any>;
  const crit = (st.critiques as any[]).at(-1);
  const comp = (st.compliance ?? {}) as Record<string, any>;
  const ver = (st.verification ?? {}) as Record<string, any>;
  const price = (st.price ?? {}) as Record<string, any>;
  const paragraphs: string[] = (draft.cover_letter as string).split("\n\n").filter((p) => p.trim());

  async function regenerate(i: number) {
    setRegenBusy(i);
    try {
      const r = await must(api.POST("/api/proposals/{job_id}/regenerate-paragraph", { params: { path: { job_id: id } },
        body: { index: i, instruction: "Make it more specific to the client's stated need." } }));
      setPara({ text: r.cover_letter, compliance: r.compliance });
    } finally { setRegenBusy(null); }
  }

  return (
    <>
      <div className="row between">
        <div><h1>Proposal studio</h1><p className="sub">{(st.job as any).title}</p></div>
        <div className="row"><StatusBadge status={st.pending_approval ? "waiting_approval" : st.status ?? ""} />
          <RiskBadge level={(st.risk_report as any)?.level} score={(st.risk_report as any)?.score} />
          <span className="badge">bid {money(price.amount, price.type === "hourly")}</span></div>
      </div>
      <div className="grid two">
        <div className="stack">
          <section className="card">
            <div className="row between"><h2>Cover letter <span className="small muted">v{draft.version}</span></h2>
              <span className="small muted">{(draft.cover_letter as string).split(/\s+/).length} words · hover underlined claims for evidence</span></div>
            <Letter text={draft.cover_letter} claims={st.claims as ClaimWithEvidence[]} />
            {st.pending_approval && (
              <details style={{ marginTop: 10 }}><summary className="small">Regenerate one paragraph</summary>
                {paragraphs.map((p, i) => (
                  <div key={i} className="row between small" style={{ marginTop: 6 }}>
                    <span style={{ flex: 1 }}>{p.slice(0, 90)}…</span>
                    <button className="btn" disabled={regenBusy !== null} onClick={() => regenerate(i)}>{regenBusy === i ? "…" : "Regenerate"}</button>
                  </div>))}
                {para && (<div className="banner info small" style={{ marginTop: 8 }}>
                  Suggested version below{para.compliance.allowed ? "" : " (compliance would block it)"}. Use <strong>Edit</strong> to apply it.
                  <div className="letter">{para.text}</div></div>)}
              </details>)}
          </section>
          {(draft.screening_answers as any[]).length > 0 && (
            <section className="card"><h2>Screening answers</h2>
              {(draft.screening_answers as any[]).map((a) => (<div key={a.question} style={{ marginBottom: 10 }}>
                <strong className="small">{a.question}</strong><div className="letter">{a.answer}</div></div>))}
            </section>)}
        </div>
        <div className="stack">
          {st.pending_approval && (
            <ApprovalPanel threadId={st.thread_id} original={para?.text ?? draft.cover_letter}
              preview={st.dry_run_preview as Record<string, unknown> | null} onDecided={(run) => nav(`/runs/${run}?job=${id}`)} />)}
          <section className="card"><h2>Claim verification</h2>
            <p className="small">{ver.claims_checked ?? 0} claims checked · <strong>{ver.unsupported_before ?? 0}</strong> unsupported claim(s) removed before the Critic saw the draft.</p>
            {(ver.removed ?? []).map((r: string) => <div key={r} className="banner bad small">Removed: “{r}”</div>)}
          </section>
          <section className="card"><h2>Critic</h2>
            {crit ? (<><p className="small">{crit.approve ? "Approved" : "Asked for changes"} · grounding {crit.grounding}/5 · personalisation {crit.personalisation}/5 · {(st.critiques as any[]).length - 1} revision(s)</p>
              <ul className="small">{(crit.issues ?? []).map((x: string) => <li key={x}>{x}</li>)}</ul></>) : <p className="muted small">-</p>}
          </section>
          <section className="card"><h2>Compliance</h2>
            {comp.allowed === false ? <div className="banner bad">Blocked: {comp.blocked_reason}</div> :
              <p className="small">Passed{(comp.violations ?? []).length ? ` after removing ${(comp.violations as any[]).length} item(s)` : ""}.</p>}
            {(comp.violations ?? []).map((v: any, i: number) => <div key={i} className="small"><span className="badge warn">{v.rule_id}</span> {v.action}: “{v.excerpt}”</div>)}
          </section>
          <section className="card"><h2>Price rationale</h2><p className="small">{price.rationale}</p></section>
        </div>
      </div>
    </>
  );
}
