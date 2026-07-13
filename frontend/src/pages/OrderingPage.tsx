import { useEffect, useState } from "react";
import {
  Account,
  Community,
  OrderingBoardRow,
  getOrderingBoard,
  listAccounts,
  listCommunities,
  updateOrderingChecklist,
} from "../api";
import { statusLabel } from "./JobsPage";

export const STAGES = [
  { key: "stage1", label: "1. PO's & Selection File" },
  { key: "stage2", label: "2. Orders & Layouts" },
  { key: "stage3", label: "3. SO's & Order Comparison" },
  { key: "stage4", label: "4. POs Attached" },
] as const;

export default function OrderingPage({ canWrite }: { canWrite: boolean }) {
  const [rows, setRows] = useState<OrderingBoardRow[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [accountFilter, setAccountFilter] = useState("");
  const [communityFilter, setCommunityFilter] = useState("");
  const [includeClosed, setIncludeClosed] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const params: Record<string, string> = {};
    if (accountFilter) params.account_id = accountFilter;
    if (communityFilter) params.community_id = communityFilter;
    if (includeClosed) params.include_closed = "true";
    setRows(await getOrderingBoard(params));
  }

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountFilter, communityFilter, includeClosed]);

  useEffect(() => {
    listAccounts()
      .then((all) =>
        setAccounts(
          all.filter(
            (a) => a.type === "builder" && (a.name.startsWith("DR Horton") || a.name.startsWith("Century"))
          )
        )
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    setCommunityFilter("");
    if (accountFilter) {
      listCommunities(Number(accountFilter)).then(setCommunities).catch(() => {});
    } else {
      setCommunities([]);
    }
  }, [accountFilter]);

  async function toggle(row: OrderingBoardRow, stageKey: (typeof STAGES)[number]["key"]) {
    if (!canWrite) return;
    const doneKey = `${stageKey}_done` as const;
    const updated = await updateOrderingChecklist(row.job_id, { [doneKey]: !row.checklist[doneKey] });
    setRows((rs) => rs.map((r) => (r.job_id === row.job_id ? { ...r, checklist: updated } : r)));
  }

  return (
    <div>
      <div className="page-sticky">
        <div className="page-head">
          <h2>National Builder Ordering</h2>
        </div>
        <div className="filters">
          <select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
            <option value="">All builders</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          {accountFilter && communities.length > 0 && (
            <select value={communityFilter} onChange={(e) => setCommunityFilter(e.target.value)}>
              <option value="">All communities</option>
              {communities.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          <label className="check-inline">
            <input type="checkbox" checked={includeClosed} onChange={(e) => setIncludeClosed(e.target.checked)} />
            include closed
          </label>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job code</th>
              <th>Community</th>
              <th>Lot</th>
              <th>Address</th>
              {STAGES.map((s) => (
                <th key={s.key} className="stage-col">
                  {s.label}
                </th>
              ))}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.job_id}>
                <td>
                  <a href={`#/jobs/${row.job_id}`}>{row.job_code ?? `#${row.job_id}`}</a>
                </td>
                <td>{row.community_name ?? "—"}</td>
                <td>{row.lot_number ?? "—"}</td>
                <td>{row.address}</td>
                {STAGES.map((s) => {
                  const done = row.checklist[`${s.key}_done`];
                  return (
                    <td key={s.key} className="stage-col">
                      <button
                        className={`stage-toggle ${done ? "done" : ""}`}
                        title={s.label}
                        disabled={!canWrite}
                        onClick={() => toggle(row, s.key).catch((e) => setError(e.message))}
                      >
                        {done ? "✓" : ""}
                      </button>
                    </td>
                  );
                })}
                <td>
                  <span className={`badge badge-${row.status}`}>{statusLabel(row.status)}</span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No builder jobs match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
