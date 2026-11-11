import { useCallback, useEffect, useRef, useState } from "react";

export type Load<T> = { data?: T; error?: Error; loading: boolean; reload: () => void };

/** Minimal data hook: loading / error / data states, optional polling. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], pollMs?: number): Load<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: s.data === undefined }));
    fnRef.current().then(
      (data) => alive && setState({ data, loading: false }),
      (error: Error) => alive && setState((s) => ({ ...s, error, loading: false })),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  useEffect(() => {
    if (!pollMs) return;
    const t = setInterval(() => setTick((x) => x + 1), pollMs);
    return () => clearInterval(t);
  }, [pollMs]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { ...state, reload };
}

export type RunEvent = {
  seq: number;
  type: "run" | "node" | "interrupt";
  node?: string;
  summary?: string;
  status?: string;
  error?: string | null;
  latency_ms?: number | null;
  model?: string | null;
  ts: number;
};

/** Follow a run's Server-Sent Events (replays recorded events first, so a refresh loses nothing). */
export function useRunStream(runId?: string) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<string>("connecting");
  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    setStatus("running");
    const es = new EventSource(`/api/runs/${runId}/stream`, { withCredentials: true });
    const onEv = (e: MessageEvent) => {
      const ev = JSON.parse(e.data) as RunEvent;
      setEvents((xs) => (xs.some((x) => x.seq === ev.seq) ? xs : [...xs, ev]));
      if (ev.type === "run" && ev.status && ev.status !== "running") {
        setStatus(ev.status);
        if (["done", "failed", "waiting_approval"].includes(ev.status)) es.close();
      }
    };
    ["run", "node", "interrupt"].forEach((t) => es.addEventListener(t, onEv as EventListener));
    es.onerror = () => setStatus((s) => (s === "running" ? "reconnecting" : s));
    return () => es.close();
  }, [runId]);
  return { events, status };
}
