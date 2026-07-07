import { useEffect, useMemo, useState } from "react";
import { PhaseReportRow, getPhaseReport } from "../api";
import { fmtDate } from "../format";

interface CommunityGroup {
  key: string;
  builder: string;
  community: string;
  rows: PhaseReportRow[];
}

export default function ReportsPage() {
  const [rows, setRows] = useState<PhaseReportRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getPhaseReport()
      .then((r) => {
        setRows(r);
        setSelected(new Set(r.map((row) => groupKey(row)))); // everything selected by default
        setLoaded(true);
      })
      .catch((e) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, CommunityGroup>();
    for (const row of rows) {
      const key = groupKey(row);
      if (!map.has(key)) {
        map.set(key, {
          key,
          builder: row.account_name,
          community: row.community_name ?? "(no community)",
          rows: [],
        });
      }
      map.get(key)!.rows.push(row);
    }
    return [...map.values()];
  }, [rows]);

  function toggle(key: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const selectedCount = groups.filter((g) => selected.has(g.key)).length;

  return (
    <div>
      <div className="page-sticky no-print">
        <div className="page-head">
          <h2>Reports — Phase Report</h2>
          <button onClick={() => window.print()} disabled={selectedCount === 0}>
            🖨 Print {selectedCount === groups.length ? "all" : `${selectedCount} selected`}
          </button>
        </div>
        <div className="filters">
          <button className="link-btn" onClick={() => setSelected(new Set(groups.map((g) => g.key)))}>
            select all
          </button>
          <button className="link-btn" onClick={() => setSelected(new Set())}>
            select none
          </button>
          <span className="muted" style={{ alignSelf: "center" }}>
            {selectedCount} of {groups.length} communities selected for print
          </span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {loaded && groups.length === 0 && <p className="muted">No active builder houses.</p>}

      <div className="print-title print-only">
        Carter Kitchen and Bath — Phase Report — {fmtDate(new Date().toISOString())}
      </div>

      {groups.map((g) => (
        <section key={g.key} className={`report-group ${selected.has(g.key) ? "" : "print-skip"}`}>
          <div className="report-group-head">
            <label className="check-inline no-print">
              <input type="checkbox" checked={selected.has(g.key)} onChange={() => toggle(g.key)} />
            </label>
            <h3>
              {g.builder} — {g.community}
              <span className="muted"> ({g.rows.length} house{g.rows.length === 1 ? "" : "s"})</span>
            </h3>
          </div>
          <div className="table-wrap report-table">
            <table>
              <thead>
                <tr>
                  <th>Lot</th>
                  <th>Job code</th>
                  <th>Address</th>
                  <th>Current phase</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.job_id}>
                    <td>{r.lot_number ?? "—"}</td>
                    <td>
                      <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                    </td>
                    <td>{r.address}</td>
                    <td>{r.phase_label ?? "—"}</td>
                    <td>{r.phase_date ? fmtDate(r.phase_date) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function groupKey(row: PhaseReportRow) {
  return `${row.account_name}||${row.community_name ?? ""}`;
}
