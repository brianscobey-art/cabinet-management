import { FormEvent, useEffect, useState } from "react";
import { fetchMe, getToken, login, setToken, User } from "./api";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!getToken());
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="center">Loading…</div>;
  if (!user) return <Login onLogin={setUser} error={error} setError={setError} />;

  return (
    <div className="shell">
      <header>
        <h1>Townsend Cabinet Management</h1>
        <button
          onClick={() => {
            setToken(null);
            setUser(null);
          }}
        >
          Sign out
        </button>
      </header>
      <main>
        <p>
          Signed in as <strong>{user.full_name}</strong> ({user.email}) — role:{" "}
          <strong>{user.role}</strong>
        </p>
        <p className="muted">
          Phase 0 shell. Jobs, quoting, scheduling, and the dashboard arrive in
          later phases.
        </p>
      </main>
    </div>
  );
}

function Login({
  onLogin,
  error,
  setError,
}: {
  onLogin: (u: User) => void;
  error: string;
  setError: (e: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
        <h1>Townsend Cabinet Management</h1>
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
