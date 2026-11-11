import { api, must, type Schemas } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { Empty, ErrorState, Loading } from "../../components/ui";

const pct = (x?: number | null) => (x == null ? "-" : `${Math.round(x * 100)}%`);

/** Reply/hire rate by category, Connects vs outcomes, cost and latency per proposal, top rejection reasons. */
export default function AnalyticsPage() {
  const a = useLoad<Schemas["Analytics"]>(() => must(api.GET("/api/analytics")), [], 15000);
  if (a.error) return <ErrorState error={a.error} retry={a.reload} />;
  if (!a.data) return <Loading lines={6} />;
  const d = a.data;
  const f = d.funnel;
  const max = Math.max(1, f.analysed ?? 1);
  return (
    <>
      <h1>Analytics</h1>
      <p className="sub">What GigBid did for you, and what it cost.</p>
      <div className="grid three">
        {(["analysed", "bid", "submitted", "replied", "hired"] as const).map((k) => (
          <div key={k} className="card"><div className="muted small">{k}</div><div style={{ fontSize: 26, fontWeight: 700 }}>{f[k] ?? 0}</div>
            <div className="bar"><span style={{ width: `${((f[k] ?? 0) / max) * 100}%` }} /></div></div>))}
        <div className="card"><div className="muted small">Connects spent / per reply</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{d.connects.spent as number} <span className="small muted">/ {(d.connects.connects_per_reply as number) ?? "-"}</span></div></div>
      </div>
      <div className="grid two" style={{ marginTop: 14 }}>
        <section className="card"><h2>Reply and hire rate by category</h2>
          {d.by_category.length === 0 ? <Empty>No submitted proposals yet.</Empty> : (
            <table><thead><tr><th>Category</th><th className="num">Sent</th><th className="num">Reply rate</th><th className="num">Hire rate</th></tr></thead>
              <tbody>{d.by_category.map((c: any) => <tr key={c.category}><td>{c.category}</td><td className="num">{c.submitted}</td>
                <td className="num">{pct(c.reply_rate)}</td><td className="num">{pct(c.hire_rate)}</td></tr>)}</tbody></table>)}
        </section>
        <section className="card"><h2>Cost and latency</h2>
          <table><tbody>
            <tr><td>Analyses</td><td className="num">{d.cost_latency.runs as number}</td></tr>
            <tr><td>p50 / p95 latency per job</td><td className="num">{(d.cost_latency.p50_latency_s as number)?.toFixed?.(1) ?? "-"} s / {(d.cost_latency.p95_latency_s as number)?.toFixed?.(1) ?? "-"} s</td></tr>
            <tr><td>Total model cost</td><td className="num">${(d.cost_latency.cost_usd_total as number).toFixed(4)}</td></tr>
            <tr><td>Cost per proposal</td><td className="num">{d.cost_latency.cost_usd_per_proposal != null ? `$${(d.cost_latency.cost_usd_per_proposal as number).toFixed(4)}` : "-"}</td></tr>
          </tbody></table>
        </section>
      </div>
      <section className="card" style={{ marginTop: 14 }}><h2>Top rejection reasons</h2>
        {d.top_rejection_reasons.length === 0 ? <p className="muted small">You haven't rejected any drafts.</p> :
          <ol>{d.top_rejection_reasons.map((r: any) => <li key={r.reason}>{r.reason} <span className="muted small">×{r.count}</span></li>)}</ol>}
      </section>
    </>
  );
}
