import { useEffect, useState } from "react";
import { getJobAccounts, runJobAccounts, JobAccountRow, JobAccountsReport } from "../api";
import { fmtDate } from "../format";

// Review list for the DOMO G/I job-account match (Brian 10/28/26): blank codes
// fill themselves; what is left here needs a human.
const SECTIONS: { key: keyof JobAccountsReport["lists"]; title: string; note: string }[] = [
  { key: "conflicts", title: "CabinetTron code disagrees with DOMO", note: "Left as-is. Fix the job if DOMO is right." },
  { key: "tracker_differs", title: "Tracker code disagrees with DOMO", note: "The 3.0 tracker's G-Code / I-Code column has a different account." },
  { key: "ambiguous", title: "Ashley's Code on more than one tracker house", note: "Not filled -- can't tell which house it belongs to." },
  { key: "unmatched", title: "No house in the tracker", note: "No tracker row has this Ashley's Code, G-Code or I-Code. Nothing created." },
  { key: "not_in_cabinettron", title: "In the tracker but not in CabinetTron", note: "Usually closed or void houses the import skips." },
  { key: "filled", title: "Filled on the last run", note: "Blank codes CabinetTron filled from DOMO." },
];

export default function JobAccountsView() {
  const [data, setData] = useState<JobAccountsReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getJobAccounts().then(setData).catch((e) => setError(e.message));
  }, []);

  async function rerun() {
    setBusy(true);
    setError("");
    try {
      setData(await runJobAccounts());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="filters no-print">
        <span className="muted">
          {data.at
            ? `Last match ${fmtDate(data.at.slice(0, 10))} ${data.at.slice(11, 16)} · ${data.file ?? ""} · ${data.accounts ?? 0} DOMO accounts · ${data.already_set ?? 0} jobs already set`
            : "No DOMO job-account file has been matched yet."}
        </span>
        <span style={{ flex: 1 }} />
        <button type="button" disabled={busy} onClick={rerun}>
          {busy ? "Matching…" : "Re-match now"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {SECTIONS.map((s) => {
        const rows = data.lists[s.key] ?? [];
        return (
          <section key={s.key} style={{ marginBottom: "1.25rem" }}>
            <h3 style={{ margin: "0.75rem 0 0.15rem", fontSize: "1rem" }}>
              {s.title} <span className="muted" style={{ fontWeight: 400 }}>· {rows.length}</span>
            </h3>
            <p className="muted" style={{ margin: "0 0 0.35rem" }}>{s.note}</p>
            {rows.length > 0 && <AccountTable rows={rows} />}
          </section>
        );
      })}
    </div>
  );
}

function AccountTable({ rows }: { rows: JobAccountRow[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ashley's Code</th>
            <th>Customer</th>
            <th>G-Code</th>
            <th>I-Code</th>
            <th>Set up</th>
            <th>Job code</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.g ?? ""}-${r.i ?? ""}-${r.field ?? ""}-${i}`}>
              <td>{r.name}</td>
              <td>{r.customer}</td>
              <td>{r.g ?? "—"}</td>
              <td>{r.i ?? "—"}</td>
              <td>{fmtDate(r.created)}</td>
              <td>{r.job_code ?? r.job_codes?.join(", ") ?? "—"}</td>
              <td>
                {r.field && r.cabinettron != null && `${r.field}: CabinetTron ${r.cabinettron}, DOMO ${r.domo}`}
                {r.field && r.tracker != null && `${r.field}: tracker ${r.tracker}, DOMO ${r.domo}`}
                {r.fields && `filled ${r.fields.join(" + ")} (by ${r.matched_by})`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
