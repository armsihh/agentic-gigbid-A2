import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, must } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { Empty, ErrorState, Loading, money } from "../../components/ui";

type Item = { job_id: string; title: string; snippet: string; category?: string; budget?: number | null;
  hourly_high?: number | null; payment_type: string; connects_cost: number; posted_at?: string };

/** Read-only marketplace search, to pick a job and analyse it by hand. */
export default function BrowsePage() {
  const nav = useNavigate();
  const [category, setCategory] = useState("ai_ml");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string>();
  const res = useLoad<{ items: Item[] }>(async () => (await must(api.GET("/api/marketplace/jobs", {
    params: { query: { category, query: query || undefined, limit: 25 } } }))) as { items: Item[] }, [category, query]);

  async function analyze(id: string) {
    setBusy(id);
    const r = await must(api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: id } } }));
    nav(`/runs/${r.run_id}?job=${id}`);
  }
  return (
    <>
      <h1>Browse marketplace</h1>
      <p className="sub">Live GigSim jobs. Analysing a job runs the full agent team; nothing is sent without you.</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <select value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: "auto" }} aria-label="Category">
          <option value="ai_ml">AI / ML</option><option value="web_dev">Web dev</option>
          <option value="data_analysis">Data analysis</option><option value="other">Other</option>
        </select>
        <input placeholder="Keywords" value={query} onChange={(e) => setQuery(e.target.value)} style={{ maxWidth: 320 }} aria-label="Keywords" />
      </div>
      <div className="card">
        {res.error && <ErrorState error={res.error} retry={res.reload} />}
        {res.loading && <Loading />}
        {res.data && res.data.items.length === 0 && <Empty>No open jobs match.</Empty>}
        {res.data?.items.map((j) => (
          <div key={j.job_id} className="row between" style={{ borderBottom: "1px solid var(--border)", padding: "10px 0" }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <strong>{j.title}</strong>
              <div className="small muted">{j.snippet.slice(0, 180)}…</div>
              <div className="small">{j.payment_type === "hourly" ? money(j.hourly_high, true) : money(j.budget)} · {j.connects_cost} Connects</div>
            </div>
            <button className="btn primary" disabled={busy === j.job_id} onClick={() => analyze(j.job_id)} data-testid="analyze">
              {busy === j.job_id ? "Starting…" : "Analyse"}
            </button>
          </div>
        ))}
      </div>
    </>
  );
}
