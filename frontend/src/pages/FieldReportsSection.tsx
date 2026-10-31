import { useEffect, useState } from "react";
import { JobFieldReports, getJobFieldReports } from "../api";
import { fmtDate } from "../format";

const yn = (v: boolean | null) => (v === null ? "—" : v ? "Yes" : "No");

// Installer sign-offs ("Install Reports") and the old QC v2 post walks, read
// hourly from Smartsheet (Brian 10/30/26). Hidden when the job has neither.
export default function FieldReportsSection({ jobId }: { jobId: number }) {
  const [data, setData] = useState<JobFieldReports | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    getJobFieldReports(jobId).then(setData).catch(() => setData(null));
  }, [jobId]);

  if (!data || (data.install_reports.length === 0 && data.qc_reports.length === 0)) return null;

  return (
    <>
      <h3 className="kb-head">Install & post-walk reports</h3>
      {data.install_reports.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Installed</th>
                <th>Installer</th>
                <th>Complete?</th>
                <th>Trade stopping?</th>
                <th>Needed to finish</th>
                <th>Damage / parts</th>
                <th className="num">Shoe sticks</th>
                <th>CabinetTron did</th>
              </tr>
            </thead>
            <tbody>
              {data.install_reports.map((r, i) => (
                <tr key={i}>
                  <td>{fmtDate(r.install_date)}</td>
                  <td>{r.installer ?? "—"}</td>
                  <td style={r.complete === false ? { color: "#EE6E6E", fontWeight: 600 } : undefined}>{yn(r.complete)}</td>
                  <td style={r.trade_stopping ? { color: "#EE6E6E", fontWeight: 600 } : undefined}>{yn(r.trade_stopping)}</td>
                  <td>{r.needed_to_finish ?? "—"}</td>
                  <td>{r.damage_parts ? r.damage_detail ?? "Yes" : yn(r.damage_parts)}</td>
                  <td className="num">{r.shoe_sticks ?? "—"}</td>
                  <td className="muted">{r.actions ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.qc_reports.map((q, i) => (
        <div key={i} className="card" style={{ marginTop: "0.5rem" }}>
          <b>QC post walk {fmtDate(q.walked_at)}</b>
          <span className="muted"> · {q.walked_by ?? "—"} · </span>
          <span style={q.result === "issues" ? { color: "#EE6E6E", fontWeight: 600 } : undefined}>{q.result}</span>
          <p style={{ margin: "0.35rem 0" }}>{q.summary}</p>
          <button className="link-btn" onClick={() => setOpen(open === i ? null : i)}>
            {open === i ? "hide answers" : "all answers"}
          </button>
          {open === i && (
            <dl style={{ marginTop: "0.5rem" }}>
              {Object.entries(q.answers).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
    </>
  );
}
