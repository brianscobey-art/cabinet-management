import { FormEvent, useEffect, useState } from "react";
import { fetchMe, getToken, login, runFeedSync, setToken, User } from "./api";
import AccountsPage from "./pages/AccountsPage";
import JobDetailPage from "./pages/JobDetailPage";
import ServiceRequestPage from "./pages/ServiceRequestPage";
import ServiceFormsPage from "./pages/ServiceFormsPage";
import BlankServiceForm from "./pages/BlankServiceForm";
import FormsPage from "./pages/FormsPage";
import JobsPage from "./pages/JobsPage";
import OrderingPage from "./pages/OrderingPage";
import PhasesPage from "./pages/PhasesPage";
import ReportsPage from "./pages/ReportsPage";
import SchedulePage from "./pages/SchedulePage";

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/jobs");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/jobs");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

const WRITE_ROLES = ["sales", "admin"];

const FEED_LABELS: Record<string, string> = {
  vendorsuite: "VS Combined PO & Schedule",
  century: "Century SupplyPro",
  new_orders: "New Orders Status",
};

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!getToken());
  const [syncing, setSyncing] = useState(false);
  const [toast, setToast] = useState("");
  const hash = useHashRoute();

  // show the sync summary saved just before the post-update reload
  useEffect(() => {
    const saved = sessionStorage.getItem("syncResult");
    if (saved) {
      sessionStorage.removeItem("syncResult");
      setToast(saved);
      const t = setTimeout(() => setToast(""), 10000);
      return () => clearTimeout(t);
    }
  }, []);

  async function handleUpdate() {
    setSyncing(true);
    try {
      const result = await runFeedSync();
      const lines = Object.entries(result).map(([key, r]) => {
        const name = FEED_LABELS[key] ?? key;
        if (r.error) return `${name}: ${r.error}`;
        const bits = [
          r.created ? `${r.created} new` : "",
          r.updated ? `${r.updated} updated` : "",
          !r.created && !r.updated ? "no changes" : "",
        ].filter(Boolean);
        return `${name} (${r.file ?? ""}): ${bits.join(", ")}`;
      });
      sessionStorage.setItem("syncResult", `Updated from stored reports\n${lines.join("\n")}`);
      window.location.reload();
    } catch (err) {
      setToast(`Update failed: ${err instanceof Error ? err.message : "unknown error"}`);
      setSyncing(false);
      setTimeout(() => setToast(""), 10000);
    }
  }

  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="center">Loading…</div>;
  if (!user) return <Login onLogin={setUser} />;

  const canWrite = WRITE_ROLES.includes(user.role);
  // field crews log phases from the community, so they get write access there
  const canWritePhases = [...WRITE_ROLES, "field", "installer_coordinator"].includes(user.role);
  const jobMatch = hash.match(/^#\/jobs\/(\d+)$/);
  const serviceMatch = hash.match(/^#\/service\/(\d+)$/);

  let page;
  if (serviceMatch)
    page = <ServiceRequestPage srId={Number(serviceMatch[1])} canWrite={canWritePhases} />;
  else if (hash.startsWith("#/service-blank")) page = <BlankServiceForm />;
  else if (hash.startsWith("#/forms/service")) page = <ServiceFormsPage canWrite={canWritePhases} />;
  else if (jobMatch) page = <JobDetailPage jobId={Number(jobMatch[1])} canWrite={canWrite} />;
  else if (hash.startsWith("#/accounts")) page = <AccountsPage canWrite={canWrite} />;
  else if (hash.startsWith("#/ordering")) page = <OrderingPage canWrite={canWrite} />;
  else if (hash.startsWith("#/schedule")) page = <SchedulePage />;
  else if (hash.startsWith("#/phases")) page = <PhasesPage canWrite={canWritePhases} />;
  else if (hash.startsWith("#/reports")) page = <ReportsPage hash={hash} />;
  else if (hash.startsWith("#/forms")) page = <FormsPage />;
  else if (hash.startsWith("#/archive")) page = <JobsPage archived />;
  else page = <JobsPage />;

  return (
    <div className="shell">
      <header>
        <h1>
          <img src="/carter-logo.png" alt="Carter Lumber" className="logo" />
          <span>Carter Kitchen and Bath</span>
        </h1>
        {canWrite && (
          <button
            className="update-btn"
            onClick={handleUpdate}
            disabled={syncing}
            title="Pull the latest stored reports (VS Combined, Century, New Orders) into the app"
          >
            {syncing ? "⟳ Updating…" : "⟳ Update"}
          </button>
        )}
        <nav>
          <a
            href="#/jobs"
            className={
              !hash.startsWith("#/accounts") &&
              !hash.startsWith("#/ordering") &&
              !hash.startsWith("#/schedule") &&
              !hash.startsWith("#/phases") &&
              !hash.startsWith("#/reports") &&
              !hash.startsWith("#/forms") &&
              !hash.startsWith("#/archive")
                ? "active"
                : ""
            }
          >
            Jobs
          </a>
          <a href="#/ordering" className={hash.startsWith("#/ordering") ? "active" : ""}>
            Ordering
          </a>
          <a href="/ordering-platform">Platform</a>
          <a href="#/schedule" className={hash.startsWith("#/schedule") ? "active" : ""}>
            Schedule
          </a>
          <a href="#/phases" className={hash.startsWith("#/phases") ? "active" : ""}>
            Phases
          </a>
          <a href="#/accounts" className={hash.startsWith("#/accounts") ? "active" : ""}>
            Accounts
          </a>
          <a href="#/forms" className={hash.startsWith("#/forms") ? "active" : ""}>
            Forms
          </a>
          <a href="#/reports" className={hash.startsWith("#/reports") ? "active" : ""}>
            Reports
          </a>
          <a href="#/archive" className={hash.startsWith("#/archive") ? "active" : ""}>
            Archive
          </a>
        </nav>
        <div className="header-right">
          <a className="cal-btn" href="#/schedule" title="Open the install calendar">
            📅 Install Calendar
          </a>
          <span className="who">
            {user.full_name} · {user.role}
          </span>
          <button
            onClick={() => {
              setToken(null);
              setUser(null);
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      {toast && <div className="toast">{toast}</div>}
      <main>{page}</main>
    </div>
  );
}

function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      // pasted addresses often carry Outlook's mailto: prefix or whitespace
      await login(email.trim().replace(/^mailto:/i, ""), password.trim());
      onLogin(await fetchMe());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="login" onSubmit={submit}>
        <div className="login-brand">
          <img src="/carter-logo.png" alt="Carter Lumber" />
        </div>
        <h1>Carter Kitchen and Bath</h1>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value.replace(/^mailto:/i, "").trim())}
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
