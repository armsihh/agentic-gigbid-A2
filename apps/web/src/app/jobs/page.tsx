import { Link, useParams } from "react-router-dom";
import { api, must, type JobDetail } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { ActionBadge, ErrorState, Fit, Loading, money, RiskBadge, StatusBadge } from "../../components/ui";

type Match = { requirement: string; status: string; evidence_ids: string[]; note: string };
type Flag = { type: string; severity: string; evidence: string };

/** JobSpec, risk report, requirement-to-evidence matrix, price rationale, bid/skip reasoning. */
export default function JobPage() {
  const { id = "" } = useParams();
  const d = useLoad<JobDetail>(() => must(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } })), [id], 6000);
  if (d.error) return <ErrorState error={d.error} retry={d.reload} />;
  if (!d.data) return <Loading lines={8} />;
  const j = d.data;
  const job = j.job as Record<string, any>;
  const spec = (j.job_spec ?? {}) as Record<string, any>;
  const risk = (j.risk_report ?? {}) as Record<string, any>;
  const fit = (j.fit_report ?? {}) as Record<string, any>;
  const dec = (j.decision ?? {}) as Record<string, any>;
  const price = (j.price ?? {}) as Record<string, any>;
  const ev = Object.fromEntries((j.evidence as any[]).map((e) => [e.evidence_id, e]));
  return (
    <>
      <div className="row between">
        <div><h1>{job.title}</h1>
          <p className="sub">{job.payment_type === "hourly" ? `${money(job.hourly_low, true)}–${money(job.hourly_high, true)}` : money(job.budget)}
            {" "}· {job.connects_cost} Connects · {job.category} · posted {job.posted_at?.slice(0, 10)}</p></div>
        <div className="row"><StatusBadge status={j.halt ?? j.status ?? "running"} />
          {j.pending_approval && <Link className="btn primary" to={`/studio/${id}`}>Review proposal</Link>}
          {!j.pending_approval && j.has_draft && <Link className="btn" to={`/studio/${id}`}>Open proposal</Link>}</div>
      </div>
      {(j.errors ?? []).length > 0 && <div className="banner warn">{(j.errors ?? []).join(" · ")}</div>}

      <div className="grid two">
        <section className="card" aria-labelledby="dec">
          <h2 id="dec">Recommendation <ActionBadge action={dec.action} /></h2>
          <ul>{(dec.reasons ?? []).map((r: string) => <li key={r}>{r}</li>)}</ul>
          <div className="row"><span className="muted small">Fit</span><Fit value={fit.score} /></div>
        </section>
        <section className="card" aria-labelledby="risk">
          <h2 id="risk">Risk report <RiskBadge level={risk.level} score={risk.score} /></h2>
          <p className="small">{risk.explanation}</p>
          {(risk.flags ?? []).length > 0 && (
            <table><tbody>{(risk.flags as Flag[]).map((f, i) => (
              <tr key={i}><td><span className={`badge ${f.severity === "high" ? "bad" : f.severity === "medium" ? "warn" : ""}`}>{f.type}</span></td>
                <td className="small">“{f.evidence}”</td></tr>))}</tbody></table>
          )}
          {risk.injection_detected && <div className="banner warn small">This post contains instructions aimed at AI tools. GigBid ignored them.</div>}
        </section>
      </div>

      <section className="card" style={{ marginTop: 14 }} aria-labelledby="mx">
        <h2 id="mx">Requirements → portfolio evidence</h2>
        {(fit.matches ?? []).length === 0 ? <p className="muted">No requirements analysed yet.</p> : (
          <table className="matrix">
            <thead><tr><th>Requirement</th><th>Status</th><th>Evidence that proves it</th></tr></thead>
            <tbody>{(fit.matches as Match[]).map((m) => (
              <tr key={m.requirement}><td>{m.requirement}</td>
                <td><span className={`badge ${m.status === "covered" ? "ok" : m.status === "partial" ? "warn" : "bad"}`}>{m.status}</span></td>
                <td>{m.evidence_ids.length === 0 ? <span className="muted small">none in portfolio</span> :
                  m.evidence_ids.map((e) => <div key={e} className="small"><span className="badge info">{ev[e]?.source ?? e}</span> {(ev[e]?.text ?? "").slice(0, 120)}</div>)}</td>
              </tr>))}</tbody>
          </table>)}
      </section>

      <div className="grid two" style={{ marginTop: 14 }}>
        <section className="card" aria-labelledby="spec">
          <h2 id="spec">Job spec</h2>
          <p>{spec.summary}</p>
          {spec.deliverables?.length > 0 && <><strong className="small">Deliverables</strong><ul>{spec.deliverables.map((x: string) => <li key={x}>{x}</li>)}</ul></>}
          {spec.screening_questions?.length > 0 && <><strong className="small">Screening questions</strong><ul>{spec.screening_questions.map((q: any) => <li key={q.question}>{q.question}</li>)}</ul></>}
          {spec.hidden_needs?.length > 0 && <><strong className="small">Hidden needs</strong><ul>{spec.hidden_needs.map((x: string) => <li key={x}>{x}</li>)}</ul></>}
        </section>
        <section className="card" aria-labelledby="price">
          <h2 id="price">Price</h2>
          {price.amount ? (<>
            <p style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{money(price.amount, price.type === "hourly")}</p>
            <p className="small muted">Fair band {money(price.band_low)}–{money(price.band_high)} · {price.connects_cost} Connects ·
              {price.connects_worth_it ? " worth the Connects" : " not worth the Connects"}</p>
            <p className="small">{price.rationale}</p></>) : <p className="muted">Priced only for jobs worth bidding on.</p>}
        </section>
      </div>

      <section className="card" style={{ marginTop: 14 }}>
        <h2>Original post <span className="badge">untrusted client text</span></h2>
        <div className="letter small">{job.description}</div>
      </section>
      <section className="card" style={{ marginTop: 14 }}>
        <div className="row between"><h2>Decision trace</h2><Link to="/runs" className="small">all runs</Link></div>
        <ol className="timeline">{(j.trace as any[]).map((t, i) => (
          <li key={i}><span className="dot" /><div><strong>{t.node}</strong> <span className="small muted">{t.at?.slice(11, 19)}</span>
            <div className="small">{t.summary}</div></div></li>))}</ol>
      </section>
    </>
  );
}
