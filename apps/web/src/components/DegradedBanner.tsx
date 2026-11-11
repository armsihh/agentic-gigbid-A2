import { api, type Health } from "../lib/api/client";
import { useLoad } from "../lib/hooks";

/** Polls /api/health; when the marketplace is unreachable, says so and that work is queued, not lost. */
export function DegradedBanner() {
  const h = useLoad<Health | undefined>(async () => (await api.GET("/api/health")).data, [], 15000);
  if (h.error) {
    return <div className="banner bad" role="alert" data-testid="api-down">GigBid's server is not reachable. Retrying…</div>;
  }
  if (h.data && h.data.marketplace !== "ok") {
    return (
      <div className="banner bad" role="alert" data-testid="degraded-banner">
        <strong>Marketplace unavailable.</strong> New analyses and sends are queued and will resume automatically
        when it recovers. Nothing has been lost.
        {h.data.marketplace_detail && <div className="small mono">{h.data.marketplace_detail}</div>}
      </div>
    );
  }
  return null;
}
