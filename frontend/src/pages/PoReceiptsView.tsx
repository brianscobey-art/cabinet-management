import { useEffect, useState } from "react";
import { getPoReceipts, PoReceiptsReport, refreshPoReceipts } from "../api";
import { fmtDate } from "../format";

// Always dollars AND cents — never rounded (Brian's rule for this report).
const money = (n: number | null) =>
  n == null
    ? "—"
    : "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PoReceiptsView() {
  const [data, setData] = useState<PoReceiptsReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"received" | "awaiting">("received");
  const [q, setQ] = useState("");

  const load = () => getPoReceipts().then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      await refreshPoReceipts();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const term = q.trim().toLowerCase();
  const rows = data.rows.filter(
    (r) =>
      !term ||
      [r.job_code, r.order_number, r.address, r.community_name, r.vendor, r.receipt_number]
        .some((v) => v && v.toLowerCase().includes(term))
  );
  const out = data.outstanding.filter(
    (r) =>
      !term ||
      [r.job_code, r.order_number, r.address, r.community_name, r.vendor].some(
        (v) => v && v.toLowerCase().includes(term)
      )
  );

  return (
    <div>
      <div className="mr-toolbar">
        <button onClick={refresh} disabled={busy}>{busy ? "Refreshing…" : "⟳ Update from DOMO"}</button>
        <input
          type="search"
          placeholder="Search job, PO, community…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ maxWidth: 300 }}
        />
      </div>

      <div className="mr-tiles" style={{ marginBottom: 14 }}>
        <div className="mr-tile"><div className="mr-tile-label">Received this month</div>
          <div className="mr-tile-big">{data.received_this_month}</div></div>
        <div className="mr-tile"><div className="mr-tile-label">Our receipts (total)</div>
          <div className="mr-tile-big">{data.total_receipts}</div></div>
        <div className="mr-tile"><div className="mr-tile-label">Awaiting delivery</div>
          <div className="mr-tile-big">{data.outstanding_count}</div>
          <div className="mr-tile-sub">ordered, not received</div></div>
      </div>

      <div className="filters">
        <button
          className={tab === "received" ? "" : "ghost-tab"}
          style={tab === "received" ? undefined : { background: "#e7efee", color: "#125952" }}
          onClick={() => setTab("received")}
        >
          Received ({rows.length})
        </button>
        <button
          style={tab === "awaiting" ? undefined : { background: "#e7efee", color: "#125952" }}
          onClick={() => setTab("awaiting")}
        >
          Awaiting delivery ({out.length})
        </button>
      </div>

      {tab === "received" ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th><th>Community</th><th>Address</th>
                <th>PO #</th><th>Received</th><th>Vendor</th>
                <th className="r">Cost</th><th>Warehouse</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.receipt_number}>
                  <td>{r.job_id ? <a href={`#/jobs/${r.job_id}`}>{r.job_code}</a> : (r.job_code ?? "—")}</td>
                  <td>{r.community_name ?? "—"}</td>
                  <td>{r.address ?? "—"}</td>
                  <td>{r.order_number}</td>
                  <td>{fmtDate(r.receipt_date)}</td>
                  <td>{r.vendor ?? r.supplier ?? "—"}</td>
                  <td className="r">{money(r.supplier_cost)}</td>
                  <td>{r.pos ?? "—"}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={8} className="muted">No receipts{term ? " match" : " yet"}.</td></tr>}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th><th>Community</th><th>Address</th><th>PO #</th>
                <th>Vendor</th><th>Ordered</th><th>Due</th><th className="r">Overdue</th>
              </tr>
            </thead>
            <tbody>
              {out.map((r) => (
                <tr key={r.order_number} style={r.days_overdue ? { background: "#fdeeee" } : undefined}>
                  <td>{r.job_id ? <a href={`#/jobs/${r.job_id}`}>{r.job_code}</a> : (r.job_code ?? "—")}</td>
                  <td>{r.community_name ?? "—"}</td>
                  <td>{r.address ?? "—"}</td>
                  <td>{r.order_number}</td>
                  <td>{r.vendor ?? "—"}</td>
                  <td>{fmtDate(r.order_date)}</td>
                  <td>{fmtDate(r.tent_due_date)}</td>
                  <td className="r">{r.days_overdue ? `${r.days_overdue} d` : "—"}</td>
                </tr>
              ))}
              {out.length === 0 && <tr><td colSpan={8} className="muted">Nothing awaiting delivery.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
