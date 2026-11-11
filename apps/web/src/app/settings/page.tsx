import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, must, type Me } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { Empty, ErrorState, Loading } from "../../components/ui";

/** Autonomy, budgets, saved searches, connected accounts, portfolio upload, and the memory viewer. */
export default function SettingsPage({ me, onChange }: { me: Me; onChange: (m: Me) => void }) {
  const [q] = useSearchParams();
  const s = (me.settings ?? {}) as Record<string, any>;
  const [rate, setRate] = useState(String(s.hourly_rate ?? ""));
  const [floor, setFloor] = useState(String(s.min_fixed_budget ?? ""));
  const [connects, setConnects] = useState(String(s.weekly_connects_budget ?? ""));
  const [autoSkip, setAutoSkip] = useState(Boolean(s.autonomy?.auto_skip_low_fit));
  const [msg, setMsg] = useState<string>();
  const searches = useLoad(() => must(api.GET("/api/saved-searches")), []);
  const memory = useLoad(() => must(api.GET("/api/memory")), []);
  const upwork = useLoad(() => must(api.GET("/api/auth/upwork/status")), []);
  const [newSearch, setNewSearch] = useState({ name: "", query: "", category: me.persona });
  useEffect(() => { if (q.get("welcome")) setMsg("Welcome! Review your settings, add a saved search, then go to the inbox."); }, [q]);

  async function save() {
    const m = await must(api.PUT("/api/settings", { body: { hourly_rate: Number(rate) || undefined, min_fixed_budget: Number(floor) || undefined,
      weekly_connects_budget: Number(connects) || undefined, autonomy: { auto_skip_low_fit: autoSkip } } }));
    onChange(m);
    setMsg("Saved.");
  }
  async function addSearch() {
    await must(api.POST("/api/saved-searches", { body: { name: newSearch.name || "search", query: newSearch.query || undefined,
      category: newSearch.category as any, skills: [], interval_minutes: 60 } }));
    setNewSearch({ ...newSearch, name: "", query: "" });
    searches.reload();
  }
  async function removeSearch(id: number) {
    await must(api.DELETE("/api/saved-searches/{sid}", { params: { path: { sid: id } } }));
    searches.reload();
  }
  async function forget(kind: string, key: string) {
    await must(api.DELETE("/api/memory/{kind}/{key}", { params: { path: { kind, key } } }));
    memory.reload();
  }
  async function connectUpwork() {
    try {
      const r = (await must(api.POST("/api/auth/upwork/connect"))) as { authorization_url: string };
      window.open(r.authorization_url, "_blank", "noopener");
    } catch (e) { setMsg((e as Error).message); }
  }
  async function upload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const r = await fetch("/api/portfolio/upload", { method: "POST", body: fd, credentials: "include" });
    setMsg(r.ok ? "Uploaded. It is searchable on the next analysis." : `Upload failed (${r.status})`);
    if (r.ok) e.currentTarget.reset();
  }

  return (
    <>
      <h1>Settings</h1>
      <p className="sub">{me.email} · persona {me.persona} · marketplace {me.marketplace}</p>
      {msg && <div className="banner info" role="status">{msg}</div>}
      <div className="grid two">
        <section className="card stack"><h2>Rates, budgets and autonomy</h2>
          <div className="grid three">
            <label>Hourly rate ($)<input type="number" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
            <label>Min fixed ($)<input type="number" value={floor} onChange={(e) => setFloor(e.target.value)} /></label>
            <label>Connects / week<input type="number" value={connects} onChange={(e) => setConnects(e.target.value)} /></label>
          </div>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={autoSkip} onChange={(e) => setAutoSkip(e.target.checked)} />
            Auto-skip low-fit jobs (GigBid never sends anything automatically)
          </label>
          <button className="btn primary" onClick={save}>Save settings</button>
        </section>
        <section className="card stack"><h2>Connected accounts</h2>
          <div className="row between"><span>GigSim (simulated marketplace)</span><span className="badge ok">connected</span></div>
          <div className="row between"><span>Upwork (official MCP, OAuth 2.1)</span>
            {upwork.data && (upwork.data as any).connected ? <span className="badge ok">connected</span> :
              <button className="btn" onClick={connectUpwork}>Connect Upwork</button>}</div>
          <p className="small muted">Live mode only creates drafts that you confirm on upwork.com. GigBid never scrapes or automates the website.</p>
        </section>
      </div>
      <div className="grid two" style={{ marginTop: 14 }}>
        <section className="card stack"><h2>Saved searches</h2>
          {searches.error && <ErrorState error={searches.error} />}
          {searches.loading && <Loading />}
          {(searches.data ?? []).map((x: any) => (
            <div key={x.id} className="row between"><span>{x.name} <span className="small muted">{x.category} {x.query ?? ""} · every {x.interval_minutes} min</span></span>
              <button className="btn" onClick={() => removeSearch(x.id)} aria-label={`Delete ${x.name}`}>Delete</button></div>))}
          <div className="row">
            <input placeholder="Name" value={newSearch.name} onChange={(e) => setNewSearch({ ...newSearch, name: e.target.value })} style={{ maxWidth: 140 }} aria-label="Search name" />
            <input placeholder="Keywords" value={newSearch.query} onChange={(e) => setNewSearch({ ...newSearch, query: e.target.value })} style={{ maxWidth: 160 }} aria-label="Keywords" />
            <select value={newSearch.category} onChange={(e) => setNewSearch({ ...newSearch, category: e.target.value })} style={{ width: "auto" }} aria-label="Category">
              <option value="ai_ml">AI/ML</option><option value="web_dev">Web</option><option value="data_analysis">Data</option></select>
            <button className="btn" onClick={addSearch}>Add</button>
          </div>
        </section>
        <section className="card stack"><h2>Add to your portfolio</h2>
          <form className="stack" onSubmit={upload}>
            <label>Title<input name="title" required minLength={3} /></label>
            <label>Skills (comma separated)<input name="skills" /></label>
            <label>Client industry<input name="industry" /></label>
            <label>Case study (Markdown or text file)<input name="file" type="file" accept=".md,.txt" required /></label>
            <button className="btn" type="submit">Upload</button>
          </form>
        </section>
      </div>
      <section className="card" style={{ marginTop: 14 }}><h2>What GigBid has learned (memory)</h2>
        <p className="small muted">Only promoted rules appear here: style rules need the same edit in 3 different proposals; outcome insights need
          enough outcomes for a clear difference. Delete anything you disagree with.</p>
        {memory.loading && <Loading />}
        {memory.data && (memory.data as any[]).length === 0 && <Empty>Nothing learned yet. Edit a few drafts and record some outcomes.</Empty>}
        {(memory.data as any[] | undefined)?.map((m) => (
          <div key={m.kind + m.key} className="row between" style={{ borderBottom: "1px solid var(--border)", padding: "8px 0" }}>
            <div><span className={`badge ${m.kind === "style" ? "info" : "ok"}`}>{m.kind}</span> {m.text}
              <div className="small muted">{m.detail.promotion_rule}</div></div>
            <button className="btn danger" onClick={() => forget(m.kind, m.key)}>Forget</button>
          </div>))}
      </section>
    </>
  );
}
