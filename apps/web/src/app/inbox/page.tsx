import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, must, type JobRow } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { ActionBadge, Empty, ErrorState, Fit, Loading, money, RiskBadge, StatusBadge } from "../../components/ui";

/** New jobs ranked by fit, with risk badges, recommended action, price and Connects cost. */
export default function InboxPage() {
  const nav = useNavigate();
  const [action, setAction] = useState("");
  const [showSkipped, setShowSkipped] = useState(false);
  const [msg, setMsg] = useState<string>();
  const jobs = useLoad<JobRow[]>(() => must(api.GET("/api/jobs", { params: { query: {
    action: action || undefined, include_skipped: showSkipped } } })), [action, showSkipped], 8000);

  async function scoutNow() {
    const r = await must(api.POST("/api/scout/run"));
    setMsg(`Scouting started: ${(r as { queued?: number }).queued ?? 0} new job(s) queued for analysis.`);
    jobs.reload();
  }
  async function skip(id: string) {
    await must(api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } }));
    jobs.reload();
  }

  return (
    <>
      <div className="row between">
        <div><h1>Job inbox</h1><p className="sub">Ranked by fit. Scams and low-fit jobs are skipped with a reason.</p></div>
        <div className="row">
          <Link className="btn" to="/browse">Browse marketplace</Link>
          <button className="btn primary" onClick={scoutNow}>Scout now</button>
        </div>
      </div>
      {msg && <div className="banner info" role="status">{msg}</div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <label style={{ flexDirection: "row", alignItems: "center" }}>Show
          <select value={action} onChange={(e) => setAction(e.target.value)} style={{ width: "auto" }} aria-label="Filter by action">
            <option value="">all recommendations</option><option value="bid">bid</option>
            <option value="watch">watch</option><option value="skip">skip</option>
          </select>
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={showSkipped} onChange={(e) => setShowSkipped(e.target.checked)} style={{ width: "auto" }} />
          include skipped
        </label>
      </div>
      <div className="card">
        {jobs.error && <ErrorState error={jobs.error} retry={jobs.reload} />}
        {jobs.loading && <Loading lines={5} />}
        {jobs.data && jobs.data.length === 0 && (
          <Empty>No jobs yet. Press <strong>Scout now</strong> to run your saved searches, or browse the marketplace.</Empty>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <table>
            <thead><tr><th>Job</th><th>Fit</th><th>Risk</th><th>Action</th><th className="num hide-sm">Price</th>
              <th className="num hide-sm">Connects</th><th>Status</th><th /></tr></thead>
            <tbody>
              {jobs.data.map((j) => (
                <tr key={j.thread_id} className="click" onClick={() => nav(`/jobs/${j.job_id}`)} data-testid="job-row">
                  <td><Link to={`/jobs/${j.job_id}`} onClick={(e) => e.stopPropagation()}>{j.title}</Link>
                    <div className="small muted">{j.category} · {(j.summary.reasons as string[] | undefined)?.[0] ?? ""}</div></td>
                  <td><Fit value={j.fit} /></td>
                  <td><RiskBadge level={j.risk_level} score={j.risk} /></td>
                  <td><ActionBadge action={j.action} /></td>
                  <td className="num hide-sm">{money(j.price, j.summary.payment_type === "hourly")}</td>
                  <td className="num hide-sm">{j.connects_cost ?? "-"}</td>
                  <td><StatusBadge status={j.status} /></td>
                  <td>{j.status !== "skipped" && j.status !== "submitted" && (
                    <button className="btn small" onClick={(e) => { e.stopPropagation(); skip(j.job_id); }}>Skip</button>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
