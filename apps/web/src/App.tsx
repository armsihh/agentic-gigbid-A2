import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, type Me } from "./lib/api/client";
import { useLoad } from "./lib/hooks";
import { DegradedBanner } from "./components/DegradedBanner";
import { Loading } from "./components/ui";
import AnalyticsPage from "./app/analytics/page";
import BrowsePage from "./app/browse/page";
import InboxPage from "./app/inbox/page";
import JobPage from "./app/jobs/page";
import LoginPage from "./app/login/page";
import MessagesPage from "./app/messages/page";
import PipelinePage from "./app/pipeline/page";
import { RunPage, RunsPage } from "./app/runs/page";
import SettingsPage from "./app/settings/page";
import StudioPage from "./app/studio/page";

function Shell({ me, setMe }: { me: Me; setMe: (m: Me | null) => void }) {
  const pending = useLoad(async () => (await api.GET("/api/approvals")).data ?? [], [], 10000);
  const count = (pending.data as unknown[] | undefined)?.length ?? 0;
  async function logout() {
    await api.POST("/api/auth/logout");
    setMe(null);
  }
  return (
    <div className="layout">
      <nav className="nav" aria-label="Main">
        <div className="brand"><i>G</i>GigBid</div>
        <NavLink to="/inbox">Inbox {count > 0 && <span className="badge info" aria-label={`${count} pending approvals`}>{count}</span>}</NavLink>
        <NavLink to="/pipeline">Pipeline</NavLink>
        <NavLink to="/messages">Messages</NavLink>
        <NavLink to="/runs">Agent runs</NavLink>
        <NavLink to="/analytics">Analytics</NavLink>
        <NavLink to="/settings">Settings</NavLink>
        <div className="spacer" />
        <div className="who">{me.email}<br />{me.persona} · {me.marketplace}</div>
        <button className="btn" onClick={logout}>Sign out</button>
      </nav>
      <main>
        <DegradedBanner />
        <Routes>
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/studio/:id" element={<StudioPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/messages" element={<MessagesPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/settings" element={<SettingsPage me={me} onChange={setMe} />} />
          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    api.GET("/api/auth/me").then(({ data }) => setMe(data ?? null), () => setMe(null));
  }, []);
  if (me === undefined) return <main><Loading /></main>;
  return (
    <BrowserRouter>
      {me ? <Shell me={me} setMe={setMe} /> : (
        <Routes><Route path="*" element={<LoginPage onAuth={setMe} />} /></Routes>
      )}
    </BrowserRouter>
  );
}
