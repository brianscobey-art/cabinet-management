import { FormEvent, useState } from "react";
import { setPasswordWithToken } from "../api";

/** Landing page for the emailed invite link: #/set-password?token=... */
export default function SetPasswordPage() {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // token lives in the hash query: "#/set-password?token=XYZ"
  const token = new URLSearchParams(window.location.hash.split("?")[1] || "").get("token") || "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await setPasswordWithToken(token, password);
      // Logged in now — drop the token from the URL and go to the app home.
      window.location.hash = "#/suite";
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not set password");
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="login" onSubmit={submit}>
        <img src="/carter-logo.png" alt="Carter Lumber" style={{ height: 34, marginBottom: 8 }} />
        <h2 style={{ margin: "0 0 4px" }}>Set your password</h2>
        {token ? (
          <>
            <p className="muted" style={{ marginTop: 0 }}>
              Choose a password to finish setting up your account.
            </p>
            <label>
              New password
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                required
              />
            </label>
            <label>
              Confirm password
              <input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                minLength={8}
                required
              />
            </label>
            {error && <p className="error">{error}</p>}
            <button type="submit" disabled={busy}>
              {busy ? "Saving…" : "Set password & sign in"}
            </button>
          </>
        ) : (
          <p className="error">
            This link is missing its code. Open the link from your invite email again, or ask your
            admin to resend it.
          </p>
        )}
      </form>
    </div>
  );
}
