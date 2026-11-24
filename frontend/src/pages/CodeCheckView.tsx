import { useEffect, useMemo, useState } from "react";
import { CodeCheckReport, CodeFlag, fixCodeFlag, getCodeCheck, runCodeCheck, setCodeFlagStatus } from "../api";
import { fmtDate } from "../format";

// Code Check (Brian 11/24/26): jobs whose I-/G-code doesn't match DOMO.
// DOMO is the source of truth; the suggested DOMO code is applied only when
// someone clicks Fix. A flag closes itself when the next run finds a match.
const STATUSES = [
  ["open", "Open"],
  ["fixed", "Fixed"],
  ["ignored", "Ignored"],
  ["all", "All"],
] as const;

export default function CodeCheckView() {
  const [status, setStatus] = useState("open");
  const [ksr, setKsr] = useState("");
  const [flag, setFlag] = useState("");
  const [data, setData] = useState<CodeCheckReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | "run" | null>(null);
  const [note, setNote] = useState("");

  async function load(s = status) {
    setError("");
    try {
      setData(await getCodeCheck(s));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  useEffect(() => {
    load(status);
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(
    () =>
      (data?.flags ?? []).filter(
        (f) => (!ksr || (f.ksr || "(no KSR)") === ksr) && (!flag || f.flag === flag),
      ),
    [data, ksr, flag],
  );
  const ksrs = useMemo(() => [...new Set((data?.flags ?? []).map((f) => f.ksr || "(no KSR)"))].sort(), [data]);
  const kinds = useMemo(() => [...new Set((data?.flags ?? []).map((f) => f.flag))], [data]);

  async function fix(f: CodeFlag) {
    const what = f.field === "I" ? "I-code" : "G-code";
    if (!window.confirm(`Set ${f.job_code}'s ${what} to ${f.domo_code}?\n(now: ${f.stored_code || "blank"})`)) return;
    setBusy(f.id);
    try {
      const r = await fixCodeFlag(f.id);
      setNote(`${r.job_code}: ${what} ${r.before || "blank"} → ${r.after}`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function mark(f: CodeFlag, s: "open" | "ignored") {
    setBusy(f.id);
    try {
      await setCodeFlagStatus(f.id, s);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runNow() {
    setBusy("run");
    setError("");
    try {
      await runCodeCheck();
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const s = data?.summary;
  const today = data?.today;
  return (
    <>
      {today && (
        <div className="card" style={{ marginBottom: "0.8rem" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem 1.6rem", alignItems: "baseline" }}>
            <b>
              {today.open} open flag{today.open === 1 ? "" : "s"}
            </b>
            <span>{today.new_since_yesterday} new since yesterday</span>
            {Object.entries(today.open_by_ksr).map(([k, n]) => (
              <span key={k}>
                {k}: <b>{n}</b>
              </span>
            ))}
          </div>
          {s && (
            <p className="muted" style={{ margin: "0.3rem 0 0" }}>
              Last check {fmtDate(s.date)}: {s.jobs} jobs against {s.domo_accounts} DOMO accounts and{" "}
              {s.setup_requests} setup requests · {s.new} new · {s.fixed} closed as matching DOMO
            </p>
          )}
        </div>
      )}

      <div className="filters">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <select value={ksr} onChange={(e) => setKsr(e.target.value)}>
          <option value="">All KSRs</option>
          {ksrs.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <select value={flag} onChange={(e) => setFlag(e.target.value)}>
          <option value="">All flags</option>
          {kinds.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <button onClick={runNow} disabled={busy !== null}>
          {busy === "run" ? "Checking…" : "Re-check now"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {note && <p className="muted">{note}</p>}
      {data && rows.length === 0 && <p className="muted">Nothing here.</p>}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job Code</th>
                <th>KSR</th>
                <th>Builder</th>
                <th style={{ textAlign: "center" }}>Field</th>
                <th>Stored Code</th>
                <th>DOMO Code</th>
                <th>Flag</th>
                <th>DOMO Account Name</th>
                <th style={{ textAlign: "center" }}>First Seen</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id}>
                  <td>{f.job_id ? <a href={`#/jobs/${f.job_id}`}>{f.job_code}</a> : f.job_code}</td>
                  <td>{f.ksr || "—"}</td>
                  <td>{f.builder || "—"}</td>
                  <td style={{ textAlign: "center" }}>{f.field}</td>
                  <td>{f.stored_code || <span className="muted">blank</span>}</td>
                  <td>{f.domo_code || "—"}</td>
                  <td>
                    <span className={f.status === "open" ? "badge badge-flag" : "badge"}>{f.flag}</span>
                    {f.detail && (
                      <div className="muted" style={{ fontSize: "0.85em", maxWidth: "28rem" }}>
                        {f.detail}
                      </div>
                    )}
                  </td>
                  <td>{f.domo_name || "—"}</td>
                  <td style={{ textAlign: "center" }}>{fmtDate(f.first_seen)}</td>
                  <td>
                    {f.status === "open" ? "Open" : f.status === "fixed" ? "Fixed" : "Ignored"}
                    {f.resolved_by && f.status !== "open" && (
                      <div className="muted" style={{ fontSize: "0.85em" }}>
                        {f.resolved_by}
                        {f.resolved_at && ` ${fmtDate(f.resolved_at)}`}
                      </div>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {f.can_fix && (
                      <button onClick={() => fix(f)} disabled={busy !== null}>
                        Fix
                      </button>
                    )}{" "}
                    {f.status === "open" && (
                      <button className="secondary" onClick={() => mark(f, "ignored")} disabled={busy !== null}>
                        Ignore
                      </button>
                    )}
                    {f.status === "ignored" && (
                      <button className="secondary" onClick={() => mark(f, "open")} disabled={busy !== null}>
                        Reopen
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
