import { useEffect, useState } from "react";
import { MySummary, MySummaryJob, getMySummary } from "../api";
import { fmtDate } from "../format";

const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

const MATERIAL_COLOR: Record<string, string> = { received: "#125952", partial: "#b07a00", awaiting: "#DE2020" };

function JobCell({ j }: { j: MySummaryJob }) {
  return (
    <>
      <td>
        <a href={`#/jobs/${j.job_id}`}>{j.job_code ?? `#${j.job_id}`}</a>
      </td>
      <td>{j.address}</td>
    </>
  );
}

/** My Stuff > Summary reports for one KSR (Brian 10/29/26): received items,
 *  upcoming installs (with whether their POs are in), upcoming service. */
export default function MySummaryReports() {
  const [ksr, setKsr] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [data, setData] = useState<MySummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getMySummary(ksr, days)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [ksr, days]);

  return (
    <div className="card" style={{ marginTop: "1.25rem" }}>
      <div className="page-head" style={{ marginBottom: "0.5rem" }}>
        <h3 style={{ margin: 0 }}>Summary reports</h3>
        {data && (
          <select value={data.ksr} onChange={(e) => setKsr(e.target.value)} title="Whose jobs">
            {data.roster.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {!data ? (
        !error && <p className="muted">Loading…</p>
      ) : (
        <>
          <p className="muted" style={{ marginTop: 0 }}>
            {data.ksr} · {data.active_jobs} active jobs
          </p>

          <h4 className="kb-head">
            Received items{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ marginLeft: "0.5rem" }}>
              <option value={7}>last 7 days</option>
              <option value={30}>last 30 days</option>
              <option value={90}>last 90 days</option>
              <option value={0}>all</option>
            </select>
          </h4>
          {data.received.length === 0 ? (
            <p className="muted">Nothing received on {data.ksr}'s jobs in this window.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Received</th>
                    <th>Job</th>
                    <th>Address</th>
                    <th>Vendor</th>
                    <th>Product</th>
                    <th>Our PO #</th>
                    <th>Receipt #</th>
                    <th>Landed cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.received.map((r) => (
                    <tr key={r.receipt_number}>
                      <td>{fmtDate(r.received)}</td>
                      <JobCell j={r} />
                      <td>{r.vendor ?? "—"}</td>
                      <td>{r.product ?? "—"}</td>
                      <td>{r.our_po}</td>
                      <td>{r.receipt_number}</td>
                      <td>{money(r.landed_cost)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td colSpan={7} style={{ textAlign: "right" }}>
                      <b>{data.received.length} receipts</b>
                    </td>
                    <td>
                      <b>{money(data.received_cost)}</b>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          <h4 className="kb-head">Upcoming installs</h4>
          {data.installs.length === 0 ? (
            <p className="muted">No installs scheduled.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Install</th>
                    <th>Job</th>
                    <th>Address</th>
                    <th>Community</th>
                    <th>Status</th>
                    <th>Material</th>
                  </tr>
                </thead>
                <tbody>
                  {data.installs.map((i) => (
                    <tr key={i.job_id}>
                      <td>{fmtDate(i.install_date)}</td>
                      <JobCell j={i} />
                      <td>{i.community ?? "—"}</td>
                      <td>{i.status}</td>
                      <td style={{ color: MATERIAL_COLOR[i.material], fontWeight: 600 }}>{i.material}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h4 className="kb-head">Upcoming service</h4>
          {data.service.length === 0 ? (
            <p className="muted">No service or warranty work open.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Job</th>
                    <th>Address</th>
                    <th>What</th>
                    <th>Who</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {data.service.map((s, n) => (
                    <tr key={`${s.job_id}-${n}`}>
                      <td>
                        {s.date ? fmtDate(s.date) : "—"}
                        {!s.scheduled && s.date && <span className="muted"> (window)</span>}
                        {s.due && <div className="muted">due {fmtDate(s.due)}</div>}
                      </td>
                      <JobCell j={s} />
                      <td>{s.kind}</td>
                      <td>{s.who ?? "—"}</td>
                      <td>{s.notes ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
