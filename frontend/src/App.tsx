import { FormEvent, useEffect, useState } from "react";
import { fetchMe, getToken, login, setToken, User } from "./api";
import AccountsPage from "./pages/AccountsPage";
import JobDetailPage from "./pages/JobDetailPage";
import JobsPage from "./pages/JobsPage";
import OrderingPage from "./pages/OrderingPage";

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

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!getToken());
  const hash = useHashRoute();

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
  const jobMatch = hash.match(/^#\/jobs\/(\d+)$/);

  let page;
  if (jobMatch) page = <JobDetailPage jobId={Number(jobMatch[1])} canWrite={canWrite} />;
  else if (hash.startsWith("#/accounts")) page = <AccountsPage canWrite={canWrite} />;
  else if (hash.startsWith("#/ordering")) page = <OrderingPage canWrite={canWrite} />;
  else page = <JobsPage />;

  return (
    <div className="shell">
      <header>
        <h1>
          <img src="/carter-logo.png" alt="Carter Lumber" className="logo" />
          <span>Carter Kitchen and Bath</span>
        </h1>
        <nav>
          <a
            href="#/jobs"
            className={!hash.startsWith("#/accounts") && !hash.startsWith("#/ordering") ? "active" : ""}
          >
            Jobs
          </a>
          <a href="#/ordering" className={hash.startsWith("#/ordering") ? "active" : ""}>
            Ordering
          </a>
          <a href="#/accounts" className={hash.startsWith("#/accounts") ? "active" : ""}>
            Accounts
          </a>
        </nav>
        <div className="header-right">
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
      await login(email, password);
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
            onChange={(e) => setEmail(e.target.value)}
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
