import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, must, type Me } from "../../lib/api/client";

const PERSONAS = [
  ["ai_ml", "AI / ML engineer"],
  ["web_dev", "Full-stack web developer"],
  ["data_analysis", "Data analyst"],
] as const;

/** Sign in, or sign up + onboarding (persona, marketplace, rates, Connects budget). */
export default function LoginPage({ onAuth }: { onAuth: (m: Me) => void }) {
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [persona, setPersona] = useState<"ai_ml" | "web_dev" | "data_analysis">("ai_ml");
  const [rate, setRate] = useState("35");
  const [floor, setFloor] = useState("300");
  const [connects, setConnects] = useState("80");
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(undefined);
    try {
      let me: Me;
      if (mode === "login") {
        me = await must(api.POST("/api/auth/login", { body: { email, password } }));
      } else {
        await must(api.POST("/api/auth/register", { body: { email, password, persona } }));
        me = await must(api.PUT("/api/settings", { body: {
          hourly_rate: Number(rate), min_fixed_budget: Number(floor), weekly_connects_budget: Number(connects),
          marketplace: "gigsim", autonomy: { auto_skip_low_fit: false } } }));
      }
      onAuth(me);
      nav(mode === "register" ? "/settings?welcome=1" : "/inbox");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <form className="card stack" style={{ width: "min(440px, 100%)" }} onSubmit={submit} aria-label={mode}>
        <div className="row"><span className="badge info">GigBid</span><span className="muted small">your freelancing copilot</span></div>
        <h1>{mode === "login" ? "Sign in" : "Create your account"}</h1>
        <p className="sub">GigBid finds jobs, checks them for scams, drafts proposals backed by your portfolio, and never
          sends anything without your approval.</p>
        <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
        {mode === "register" && (
          <>
            <label>Profile
              <select value={persona} onChange={(e) => setPersona(e.target.value as typeof persona)}>
                {PERSONAS.map(([v, l]) => <option key={v} value={v}>{l} (demo persona)</option>)}
              </select>
            </label>
            <div className="grid three">
              <label>Hourly rate ($)<input type="number" min={1} value={rate} onChange={(e) => setRate(e.target.value)} /></label>
              <label>Min fixed ($)<input type="number" min={0} value={floor} onChange={(e) => setFloor(e.target.value)} /></label>
              <label>Connects / week<input type="number" min={0} value={connects} onChange={(e) => setConnects(e.target.value)} /></label>
            </div>
            <p className="small muted">You'll connect GigSim now (Upwork can be connected later in Settings) and can upload
              your own case studies after sign-up.</p>
          </>
        )}
        {err && <div className="banner bad" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy} type="submit">{mode === "login" ? "Sign in" : "Create account"}</button>
        <button type="button" className="btn" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
