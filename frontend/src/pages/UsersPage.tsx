import { FormEvent, useEffect, useState } from "react";
import {
  createUser,
  getInviteStatus,
  listUsers,
  ManagedUser,
  resendInvite,
  resetUserPassword,
  ROLES,
  updateUser,
  User,
} from "../api";

export default function UsersPage({ me }: { me: User }) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [emailEnabled, setEmailEnabled] = useState(false);

  // add-user form
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("sales");

  const refresh = () => listUsers().then(setUsers).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
    getInviteStatus().then((s) => setEmailEnabled(s.email_enabled)).catch(() => setEmailEnabled(false));
  }, []);

  async function addUser(e: FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const res = await createUser({
        email,
        full_name: fullName,
        role,
        // With email on, send an invite (no password). Without, set a temp one.
        ...(emailEnabled ? { send_invite: true } : { password }),
      });
      if (emailEnabled) {
        setNotice(
          res.invite_sent
            ? `Invite emailed to ${res.user.email}.`
            : `User added, but the invite email failed: ${res.invite_error ?? "unknown error"}. Use "resend invite".`,
        );
      } else {
        setNotice(`User added. Give them their email and the temporary password to sign in.`);
      }
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("sales");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add user");
    } finally {
      setBusy(false);
    }
  }

  async function invite(u: ManagedUser) {
    setError("");
    setNotice("");
    try {
      await resendInvite(u.id);
      setNotice(`Invite re-sent to ${u.email}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invite");
    }
  }

  async function changeRole(u: ManagedUser, newRole: string) {
    setError("");
    try {
      await updateUser(u.id, { role: newRole });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change role");
      refresh(); // snap the dropdown back to the real value
    }
  }

  async function toggleActive(u: ManagedUser) {
    setError("");
    try {
      await updateUser(u.id, { is_active: !u.is_active });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update");
    }
  }

  async function resetPw(u: ManagedUser) {
    const pw = window.prompt(`New password for ${u.full_name} (at least 8 characters):`);
    if (pw == null) return;
    if (pw.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setError("");
    try {
      await resetUserPassword(u.id, pw);
      alert(`Password updated for ${u.full_name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    }
  }

  return (
    <div>
      <div className="page-head">
        <h2>Users &amp; access</h2>
      </div>

      <form className="inline-form" onSubmit={addUser}>
        <input
          placeholder="Full name *"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
        />
        <input
          type="email"
          placeholder="Email *"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        {!emailEnabled && (
          <input
            type="text"
            placeholder="Temp password (8+ chars) *"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        )}
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          {busy ? "Adding…" : emailEnabled ? "Add & send invite" : "Add user"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: "-0.4rem" }}>
        {ROLES.find((r) => r.value === role)?.blurb}
        {emailEnabled
          ? " · They'll get an email to set their own password."
          : " · Email invites aren't set up — you'll set a temporary password and share it."}
      </p>
      {notice && <p style={{ color: "var(--green, #125952)" }}>{notice}</p>}
      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Access level</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.id === me.id;
              return (
                <tr key={u.id} style={u.is_active ? undefined : { opacity: 0.5 }}>
                  <td>
                    {u.full_name}
                    {self && <span className="muted"> (you)</span>}
                  </td>
                  <td>{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      disabled={self}
                      title={self ? "You can't change your own role" : ""}
                      onChange={(e) => changeRole(u, e.target.value)}
                    >
                      {ROLES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{u.is_active ? "Active" : "Disabled"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {emailEnabled && (
                      <>
                        <button className="link-btn" onClick={() => invite(u)}>
                          resend invite
                        </button>
                        {" · "}
                      </>
                    )}
                    <button className="link-btn" onClick={() => resetPw(u)}>
                      reset password
                    </button>
                    {!self && (
                      <>
                        {" · "}
                        <button className="link-btn" onClick={() => toggleActive(u)}>
                          {u.is_active ? "disable" : "enable"}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No users yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h3>What each access level can do</h3>
        <ul>
          {ROLES.map((r) => (
            <li key={r.value}>
              <b>{r.label}</b> — {r.blurb}
            </li>
          ))}
        </ul>
        <p className="muted">
          New people sign in with the email and temporary password you set here, then you can reset
          it anytime. Disabling a user blocks their sign-in without deleting their history.
        </p>
      </div>
    </div>
  );
}
