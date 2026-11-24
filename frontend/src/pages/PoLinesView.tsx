import { useEffect, useState } from "react";
import { PoLinesChecks, PoLinesReport, getPoLines, getPoLinesChecks } from "../api";
import { fmtDate } from "../format";

// PO Line Items (DOMO drill-down card, Brian 11/24/26): what was actually
// bought on each PO of a job, plus the checks every pull makes.
const money = (v: number | null | undefined) =>
  v == null ? "—" : `$${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;

export default function PoLinesView() {
  const [q, setQ] = useState("");
  const [data, setData] = useState<PoLinesReport | null>(null);
  const [checks, setChecks] = useState<PoLinesChecks | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getPoLinesChecks().then(setChecks).catch(() => {});
  }, []);

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError("");
    try {
      setData(await getPoLines(q.trim()));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="filters" onSubmit={search}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Job code, CAB code, I/G account or PO #"
          style={{ minWidth: "18rem" }}
        />
        <button type="submit" disabled={busy || !q.trim()}>
          {busy ? "Looking…" : "Show POs"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <p className="report-total">
            {data.job_code ? <a href={`#/jobs/${data.job_id}`}>{data.job_code}</a> : data.query}: {data.po_count} PO
            {data.po_count === 1 ? "" : "s"} · {data.item_lines} item line{data.item_lines === 1 ? "" : "s"} ·{" "}
            {money(data.items_received)} received
          </p>
          {data.pos.length === 0 && <p className="muted">No PO lines pulled for that yet.</p>}
          {data.pos.map((p) => (
            <div className="card" key={p.po_number} style={{ marginBottom: "0.8rem" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem 1.2rem", alignItems: "baseline" }}>
                <b>PO {p.po_number}</b>
                <span>{fmtDate(p.transaction_date)}</span>
                <span>
                  {p.supplier_name}
                  {p.vendor_alias && <b> ({p.vendor_alias})</b>}
                </span>
                <span className="muted">{p.carter_sku}</span>
                <span className="muted">
                  {p.account} {p.cab_job_code && `· CAB ${p.cab_job_code}`}
                </span>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem 1.2rem", margin: "0.3rem 0" }}>
                <span>Ordered {money(p.ordered_cost)}</span>
                <span>Items received {money(p.items_received)}</span>
                <span>PO feed received {p.in_feed ? money(p.feed_received) : "not in the PO feed"}</span>
                {p.in_feed && !p.received_ok && <span className="badge badge-flag">items don't add up</span>}
                {p.placeholder && <span className="badge badge-flag">$1 placeholder PO</span>}
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th style={{ textAlign: "center" }}>Qty received</th>
                      <th style={{ textAlign: "center" }}>Received cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.item_code}</td>
                        <td style={{ textAlign: "center" }}>{it.qty_received}</td>
                        <td style={{ textAlign: "center" }}>{money(it.received_cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </>
      )}

      {checks && (
        <>
          <h3 className="kb-head">Checks on the last pull ({checks.pos_checked} POs)</h3>
          <p className="muted">
            {checks.received_mismatch.length} PO{checks.received_mismatch.length === 1 ? "" : "s"} whose items don't add
            up (more than $5 off the PO feed) · {checks.placeholder_pos.length} $1 placeholder PO
            {checks.placeholder_pos.length === 1 ? "" : "s"} with items received · {checks.posted_at_cost.length}{" "}
            I-account{checks.posted_at_cost.length === 1 ? "" : "s"} posted at cost
          </p>
          {checks.received_mismatch.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>PO</th>
                    <th>Supplier</th>
                    <th>Account</th>
                    <th style={{ textAlign: "center" }}>Items received</th>
                    <th style={{ textAlign: "center" }}>PO feed received</th>
                    <th>Issue</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.received_mismatch.map((m) => (
                    <tr key={m.po_number}>
                      <td>
                        <a href="#" onClick={(e) => { e.preventDefault(); setQ(m.po_number); getPoLines(m.po_number).then(setData); }}>
                          {m.po_number}
                        </a>
                      </td>
                      <td>
                        {m.supplier}
                        {m.vendor_alias && ` (${m.vendor_alias})`}
                      </td>
                      <td>{m.account}</td>
                      <td style={{ textAlign: "center" }}>{money(m.items_received)}</td>
                      <td style={{ textAlign: "center" }}>{money(m.feed_received)}</td>
                      <td>{m.issue}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {checks.posted_at_cost.length > 0 && (
            <div className="table-wrap" style={{ marginTop: "0.6rem" }}>
              <table>
                <thead>
                  <tr>
                    <th>I-account posted at cost</th>
                    <th>G-account</th>
                    <th style={{ textAlign: "center" }}>Lines</th>
                    <th style={{ textAlign: "center" }}>Cost</th>
                    <th style={{ textAlign: "center" }}>Sales</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.posted_at_cost.map((a) => (
                    <tr key={a.i_account}>
                      <td>
                        {a.i_account} <span className="muted">{a.name}</span>
                      </td>
                      <td>{a.g_account}</td>
                      <td style={{ textAlign: "center" }}>{a.lines}</td>
                      <td style={{ textAlign: "center" }}>{money(a.cost)}</td>
                      <td style={{ textAlign: "center" }}>{money(a.sales)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
