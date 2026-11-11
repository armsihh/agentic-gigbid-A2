import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, must, type RunOut } from "../../lib/api/client";
import { useLoad, useRunStream } from "../../lib/hooks";
import { RunTimeline } from "../../components/RunTimeline";
import { Empty, ErrorState, Loading } from "../../components/ui";

/** Live node-by-node progress streamed from LangGraph, with a link to the full trace. */
export function RunPage() {
  const { id = "" } = useParams();
  const [q] = useSearchParams();
  const nav = useNavigate();
  const job = q.get("job");
  const run = useLoad<RunOut>(() => must(api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })), [id]);
  const live = useRunStream(id);
  if (run.error) return <ErrorState error={run.error} />;
  if (!run.data) return <Loading />;
  const r = run.data;
  return (
    <>
      <div className="row between">
        <div><h1>Agent run</h1><p className="sub">{r.kind} · {r.thread_id}</p></div>
        <div className="row">
          {job && live.status === "waiting_approval" && <button className="btn primary" onClick={() => nav(`/studio/${job}`)}>Review proposal</button>}
          {job && live.status !== "running" && <Link className="btn" to={`/jobs/${job}`}>Job detail</Link>}
        </div>
      </div>
      <div className="grid two">
        <div className="card"><RunTimeline events={live.events} status={live.status} /></div>
        <div className="card stack small">
          <h2>Run</h2>
          <div>Trace id: <span className="mono">{r.trace_id}</span></div>
          {r.trace_url ? <a href={r.trace_url} target="_blank" rel="noreferrer">Open full trace</a> : <span className="muted">Tracing UI not configured</span>}
          <div>Started {r.started_at.slice(0, 19).replace("T", " ")} · {r.latency_s ?? "…"} s · {r.tokens} tokens · ${r.cost_usd.toFixed(4)}</div>
          {r.error && <div className="banner bad">{r.error}</div>}
        </div>
      </div>
    </>
  );
}

export function RunsPage() {
  const nav = useNavigate();
  const runs = useLoad<RunOut[]>(() => must(api.GET("/api/runs")), [], 8000);
  return (
    <>
      <h1>Agent runs</h1>
      <p className="sub">Every analysis, approval and reply is a run you can replay.</p>
      <div className="card">
        {runs.error && <ErrorState error={runs.error} retry={runs.reload} />}
        {runs.loading && <Loading />}
        {runs.data && runs.data.length === 0 && <Empty>No runs yet.</Empty>}
        {runs.data && runs.data.length > 0 && (
          <table><thead><tr><th>Started</th><th>Kind</th><th>Thread</th><th>Status</th><th className="num">Latency</th><th className="num hide-sm">Cost</th></tr></thead>
            <tbody>{runs.data.map((r) => (
              <tr key={r.id} className="click" onClick={() => nav(`/runs/${r.id}`)}>
                <td>{r.started_at.slice(5, 16).replace("T", " ")}</td><td>{r.kind}</td>
                <td className="mono">{r.thread_id.split(":").slice(1).join(":")}</td>
                <td><span className={`badge ${r.status === "failed" ? "bad" : r.status === "waiting_approval" ? "info" : "ok"}`}>{r.status}</span></td>
                <td className="num">{r.latency_s ?? "…"} s</td><td className="num hide-sm">${r.cost_usd.toFixed(4)}</td>
              </tr>))}</tbody></table>)}
      </div>
    </>
  );
}
