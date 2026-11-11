import type { ReactNode } from "react";

export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className="banner bad" role="alert">
      {error.message} {retry && <button className="btn" onClick={retry}>Retry</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function RiskBadge({ level, score }: { level?: string | null; score?: number | null }) {
  if (score == null) return <span className="badge">risk ?</span>;
  const cls = level === "high" ? "bad" : level === "medium" ? "warn" : "ok";
  return <span className={`badge ${cls}`} title={`risk score ${score.toFixed(2)}`}>{level ?? "?"} risk</span>;
}

export function ActionBadge({ action }: { action?: string | null }) {
  if (!action) return <span className="badge">analysing</span>;
  const cls = action === "bid" ? "ok" : action === "watch" ? "warn" : "";
  return <span className={`badge ${cls}`}>{action}</span>;
}

const STATUS: Record<string, [string, string]> = {
  waiting_approval: ["needs your approval", "info"], submitted: ["submitted", "ok"], skipped: ["skipped", ""],
  watching: ["watching", "warn"], blocked: ["blocked by compliance", "bad"], rejected: ["rejected", ""],
  needs_attention: ["needs attention", "bad"], queued_marketplace_down: ["queued: marketplace down", "warn"],
  dead_letter: ["failed", "bad"], running: ["running", "info"], queued: ["queued", "info"], resuming: ["sending", "info"],
};

export function StatusBadge({ status }: { status: string }) {
  const [label, cls] = STATUS[status] ?? [status, ""];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function Fit({ value }: { value?: number | null }) {
  if (value == null) return <span className="muted">-</span>;
  return (
    <div title={`fit ${Math.round(value * 100)}%`} style={{ minWidth: 70 }}>
      <div className="bar"><span style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <div className="small muted">{Math.round(value * 100)}%</div>
    </div>
  );
}

export function money(n?: number | null, hourly = false) {
  if (n == null) return "-";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}${hourly ? "/h" : ""}`;
}
