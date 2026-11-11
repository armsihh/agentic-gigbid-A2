import { useNavigate } from "react-router-dom";
import { api, must, type JobRow } from "../../lib/api/client";
import { useLoad } from "../../lib/hooks";
import { ErrorState, Loading, money } from "../../components/ui";

const COLS = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"] as const;

/** Kanban; cards move as marketplace events arrive (the worker polls events). */
export default function PipelinePage() {
  const nav = useNavigate();
  const p = useLoad<Record<string, JobRow[]>>(() => must(api.GET("/api/pipeline")), [], 10000);
  return (
    <>
      <h1>Pipeline</h1>
      <p className="sub">Updates automatically from marketplace events (viewed, replied, interview, hired).</p>
      {p.error && <ErrorState error={p.error} retry={p.reload} />}
      {p.loading && <Loading lines={4} />}
      {p.data && (
        <div className="kanban" role="list">
          {COLS.map((c) => (
            <div key={c} className="col" role="listitem" aria-label={c} data-testid={`col-${c}`}>
              <h3>{c}<span>{p.data![c]?.length ?? 0}</span></h3>
              {(p.data![c] ?? []).map((j) => (
                <div key={j.thread_id} className="tile" tabIndex={0} onClick={() => nav(`/jobs/${j.job_id}`)}
                  onKeyDown={(e) => e.key === "Enter" && nav(`/jobs/${j.job_id}`)}>
                  <strong>{j.title.slice(0, 70)}</strong>
                  <div className="small muted">{money(j.price)} · fit {j.fit != null ? Math.round(j.fit * 100) + "%" : "-"}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
