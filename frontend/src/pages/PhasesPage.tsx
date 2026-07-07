import { useEffect, useState } from "react";
import {
  Account,
  Community,
  PhaseBoardRow,
  PhaseDef,
  getPhaseBoard,
  getPhaseDefs,
  listAccounts,
  listCommunities,
  setJobPhase,
} from "../api";
import { fmtDate } from "../format";

export default function PhasesPage({ canWrite }: { canWrite: boolean }) {
  const [phases, setPhases] = useState<PhaseDef[]>([]);
  const [builders, setBuilders] = useState<Account[]>([]);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [builderId, setBuilderId] = useState("");
  const [communityId, setCommunityId] = useState("");
  const [rows, setRows] = useState<PhaseBoardRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getPhaseDefs().then(setPhases).catch((e) => setError(e.message));
    listAccounts().then((all) => setBuilders(all.filter((a) => a.type === "builder"))).catch(() => {});
  }, []);

  useEffect(() => {
    setCommunityId("");
    setRows([]);
    if (builderId) {
      listCommunities(Number(builderId)).then(setCommunities).catch(() => {});
    } else {
      setCommunities([]);
    }
  }, [builderId]);

  useEffect(() => {
    if (communityId) {
      getPhaseBoard(Number(communityId)).then(setRows).catch((e) => setError(e.message));
    } else {
      setRows([]);
    }
  }, [communityId]);

  async function updatePhase(row: PhaseBoardRow, phase: string) {
    if (!phase) return;
    const result = await setJobPhase(row.job_id, phase);
    setRows((rs) =>
      rs.map((r) =>
        r.job_id === row.job_id
          ? {
              ...r,
              phase: result.phase,
              phase_label: phases.find((p) => p.code === result.phase)?.label ?? result.phase,
              phase_date: result.noted_at,
            }
          : r
      )
    );
  }

  return (
    <div>
      <div className="page-sticky">
        <div className="page-head">
          <h2>Phase Tracking</h2>
        </div>
        <div className="filters">
          <select value={builderId} onChange={(e) => setBuilderId(e.target.value)}>
            <option value="">Select builder…</option>
            {builders.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          {builderId && (
            <select value={communityId} onChange={(e) => setCommunityId(e.target.value)}>
              <option value="">Select community…</option>
              {communities.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          {communityId && (
            <span className="muted" style={{ alignSelf: "center" }}>
              {rows.length} active house{rows.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {!communityId ? (
        <p className="muted">Pick a builder and community to see its active houses.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lot</th>
                <th>Job code</th>
                <th>Address</th>
                <th>Current phase</th>
                <th>Plan</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.job_id}>
                  <td>{row.lot_number ?? "—"}</td>
                  <td>
                    <a href={`#/jobs/${row.job_id}`}>{row.job_code ?? `#${row.job_id}`}</a>
                  </td>
                  <td>{row.address}</td>
                  <td>
                    {canWrite ? (
                      <select
                        className={`phase-select ${row.phase ? "" : "unset"}`}
                        value={row.phase ?? ""}
                        onChange={(e) => updatePhase(row, e.target.value).catch((err) => setError(err.message))}
                      >
                        <option value="" disabled>
                          — set phase —
                        </option>
                        {phases.map((p) => (
                          <option key={p.code} value={p.code}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      row.phase_label ?? "—"
                    )}
                  </td>
                  <td>{row.plan ?? "—"}</td>
                  <td>{row.phase_date ? fmtDate(row.phase_date) : "—"}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    No active houses in this community.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
