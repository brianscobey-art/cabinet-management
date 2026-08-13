import { useEffect, useState } from "react";
import {
  disableShare,
  enableShare,
  getManagerReport,
  getPublicManagerReport,
  getShareStatus,
  ManagerReport as MR,
} from "../api";

const money = (n: number | null | undefined) =>
  n == null ? "—" : "$" + Math.round(n).toLocaleString("en-US");
const num = (n: number) => n.toLocaleString("en-US");

function Tile({ label, big, sub }: { label: string; big: string; sub?: string }) {
  return (
    <div className="mr-tile">
      <div className="mr-tile-label">{label}</div>
      <div className="mr-tile-big">{big}</div>
      {sub && <div className="mr-tile-sub">{sub}</div>}
    </div>
  );
}

/** The report body — shared by the in-app view and the public link. */
export function ManagerReportBody({ data }: { data: MR }) {
  const inst = data.installed;
  const cap = data.capacity;
  const asOf = new Date(data.as_of + "T00:00:00").toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  return (
    <div className="mr">
      <div className="mr-head">
        <div>
          <h1>Manager Sales Report</h1>
          <div className="mr-sub">Carter Kitchen &amp; Bath · as of {asOf}</div>
        </div>
      </div>

      {/* 1. Houses installed */}
      <h3 className="mr-section">Houses Installed</h3>
      <div className="mr-tiles">
        <Tile label={inst.current_month.label} big={num(inst.current_month.count)}
          sub={money(inst.current_month.po_total) + " installed"} />
        <Tile label={inst.previous_month.label} big={num(inst.previous_month.count)}
          sub={money(inst.previous_month.po_total) + " installed"} />
        <Tile label={inst.previous_quarter.label} big={num(inst.previous_quarter.count)}
          sub={money(inst.previous_quarter.po_total) + " installed"} />
        <Tile label={inst.ytd.label} big={num(inst.ytd.count)}
          sub={money(inst.ytd.po_total) + " installed"} />
      </div>

      {/* 2 + 4. Pipeline vs the official P&L number */}
      <div className="mr-callouts">
        <div className="mr-callout mr-callout-accent">
          <div className="mr-callout-label">Open Pipeline (not yet installed)</div>
          <div className="mr-callout-big">{money(data.open_pipeline.po_total)}</div>
          <div className="mr-callout-sub">{num(data.open_pipeline.count)} jobs sold &amp; in progress</div>
        </div>
        <div className="mr-callout">
          <div className="mr-callout-label">P&amp;L Net Sales (YTD, official)</div>
          <div className="mr-callout-big">
            {data.pl_net_sales?.value != null ? money(data.pl_net_sales.value) : "—"}
          </div>
          <div className="mr-callout-sub">
            {data.pl_net_sales?.source_file
              ? "from " + data.pl_net_sales.source_file
              : "P&L file not available"}
          </div>
        </div>
      </div>

      {/* 3. Sales by KSR */}
      <h3 className="mr-section">Sales by KSR — {inst.ytd.label} (sold, open + closed)</h3>
      <div className="table-wrap">
        <table className="mr-table">
          <thead>
            <tr><th>KSR</th><th className="r">Jobs sold</th><th className="r">Sales ($ PO)</th></tr>
          </thead>
          <tbody>
            {data.by_ksr.map((r) => (
              <tr key={r.ksr}>
                <td>
                  {r.ksr}
                  {r.is_new_q2 && <span className="mr-badge">new · Q2</span>}
                </td>
                <td className="r">{num(r.count)}</td>
                <td className="r">{money(r.po_total)}</td>
              </tr>
            ))}
            {data.by_ksr.length === 0 && (
              <tr><td colSpan={3} className="muted">No sales dated this year yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 5. Field capacity + travel */}
      <h3 className="mr-section">Field Capacity &amp; Coverage</h3>
      <div className="mr-tiles">
        <Tile label="Active houses" big={num(cap.active_houses)} sub="in progress now" />
        <Tile label="Field people needed" big={cap.field_people_needed?.toString() ?? "—"}
          sub={`at ${num(cap.houses_per_person)} houses/yr each`} />
        <Tile label="Coverage" big={num(cap.coverage_sq_miles)} sub="square miles" />
        <Tile label="Windshield miles / mo" big={num(cap.total_monthly_miles)}
          sub={`${cap.trips_per_job} trips/job, round-trip`} />
      </div>
      <p className="muted" style={{ margin: "6px 0 10px" }}>
        With no dedicated Field Manager, this drive falls on the KSRs — time not spent selling.
        {cap.miles_estimated ? " (Some distances are estimates until driving data finishes loading.)" : ""}
      </p>
      <div className="table-wrap">
        <table className="mr-table">
          <thead>
            <tr><th>KSR</th><th className="r">Active houses</th><th className="r">Driving miles / mo</th></tr>
          </thead>
          <tbody>
            {cap.by_ksr_miles.map((r) => (
              <tr key={r.ksr}>
                <td>{r.ksr}</td>
                <td className="r">{num(r.jobs)}</td>
                <td className="r">{num(r.monthly_miles)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** In-app view (Reports tab) with share + print controls. */
export default function ManagerReportView() {
  const [data, setData] = useState<MR | null>(null);
  const [error, setError] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getManagerReport().then(setData).catch((e) => setError(e.message));
    getShareStatus().then((s) => setToken(s.token)).catch(() => {});
  }, []);

  const shareUrl = token ? `${window.location.origin}/#/report/${token}` : "";

  async function createLink() {
    setBusy(true);
    try {
      const r = await enableShare();
      setToken(r.token);
    } finally {
      setBusy(false);
    }
  }
  async function turnOff() {
    setBusy(true);
    try {
      await disableShare();
      setToken(null);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="mr-toolbar no-print">
        <button onClick={() => window.print()}>🖨 Print / Save PDF</button>
        {token ? (
          <>
            <input className="mr-share-url" readOnly value={shareUrl} onFocus={(e) => e.target.select()} />
            <button
              onClick={() => {
                navigator.clipboard.writeText(shareUrl);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "Copied!" : "Copy link"}
            </button>
            <button className="link-btn" onClick={createLink} disabled={busy}>regenerate</button>
            <button className="link-btn" onClick={turnOff} disabled={busy}>turn off link</button>
          </>
        ) : (
          <button onClick={createLink} disabled={busy}>🔗 Create shareable link</button>
        )}
      </div>
      {token && (
        <p className="muted no-print" style={{ margin: "0 0 10px" }}>
          Anyone with this link can view the report (no login) — send it to management, and turn it off here anytime.
        </p>
      )}
      <ManagerReportBody data={data} />
    </div>
  );
}

/** Public, read-only, no-login page reached from the shareable link. */
export function PublicManagerReport({ token }: { token: string }) {
  const [data, setData] = useState<MR | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getPublicManagerReport(token).then(setData).catch((e) => setError(e.message));
  }, [token]);
  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: 20 }}>
      <div className="mr-public-brand no-print">
        <img src="/carter-logo.png" alt="Carter Lumber" style={{ height: 24 }} />
        <span>Carter Kitchen &amp; Bath</span>
        <button style={{ marginLeft: "auto" }} onClick={() => window.print()}>🖨 Print / Save PDF</button>
      </div>
      {error && <p className="error">{error}</p>}
      {data && <ManagerReportBody data={data} />}
      {!data && !error && <p className="muted">Loading…</p>}
    </div>
  );
}
