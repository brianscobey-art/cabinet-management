import { Fragment, useEffect, useState } from "react";
import {
  Account,
  Community,
  PhaseBoardRow,
  PhaseDef,
  addFieldMeasureNote,
  getPhaseBoard,
  getPhaseDefs,
  listAccounts,
  listCommunities,
  openDocument,
  setJobPhase,
  updateFieldMeasure,
} from "../api";
import { fmtDate } from "../format";

// "Brian Scobey" -> "BS"
export const initials = (name: string | null | undefined) =>
  (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0]?.toUpperCase())
    .join("") || "—";

export default function PhasesPage({ canWrite }: { canWrite: boolean }) {
  const [phases, setPhases] = useState<PhaseDef[]>([]);
  const [builders, setBuilders] = useState<Account[]>([]);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [builderId, setBuilderId] = useState("");
  const [communityId, setCommunityId] = useState("");
  const [rows, setRows] = useState<PhaseBoardRow[]>([]);
  const [error, setError] = useState("");
  const [noteFor, setNoteFor] = useState<number | null>(null); // job_id with open note editor
  const [noteText, setNoteText] = useState("");

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

  const patchRow = (jobId: number, patch: Partial<PhaseBoardRow>) =>
    setRows((rs) => rs.map((r) => (r.job_id === jobId ? { ...r, ...patch } : r)));

  async function updatePhase(row: PhaseBoardRow, phase: string) {
    if (!phase) return;
    const result = await setJobPhase(row.job_id, phase);
    patchRow(row.job_id, {
      phase: result.phase,
      phase_label: phases.find((p) => p.code === result.phase)?.label ?? result.phase,
      phase_date: result.noted_at,
    });
  }

  async function setComplete(row: PhaseBoardRow, value: string) {
    const fm = await updateFieldMeasure(row.job_id, { complete_date: value || null });
    patchRow(row.job_id, { fm_complete_date: fm.complete_date });
  }

  async function toggleCorrect(row: PhaseBoardRow) {
    const next = !row.fm_correct;
    const fm = await updateFieldMeasure(row.job_id, { correct: next });
    patchRow(row.job_id, { fm_correct: fm.correct, fm_incorrect: fm.incorrect });
  }

  async function toggleIncorrect(row: PhaseBoardRow) {
    const next = !row.fm_incorrect;
    const fm = await updateFieldMeasure(row.job_id, { incorrect: next });
    patchRow(row.job_id, { fm_incorrect: fm.incorrect, fm_correct: fm.correct });
    if (next) {
      setNoteFor(row.job_id); // checking Incorrect opens the issue note box
      setNoteText("");
    } else if (noteFor === row.job_id) {
      setNoteFor(null);
    }
  }

  async function toggleSuper(row: PhaseBoardRow) {
    const fm = await updateFieldMeasure(row.job_id, { super_notified: !row.fm_super_notified });
    patchRow(row.job_id, { fm_super_notified: fm.super_notified });
  }

  async function saveNote(row: PhaseBoardRow) {
    if (!noteText.trim()) {
      setNoteFor(null);
      return;
    }
    const note = await addFieldMeasureNote(row.job_id, noteText.trim());
    patchRow(row.job_id, { fm_notes: [note, ...row.fm_notes] });
    setNoteFor(null);
    setNoteText("");
  }

  const allNotes = rows
    .flatMap((r) => r.fm_notes.map((n) => ({ ...n, row: r })))
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

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
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Lot</th>
                  <th>Job code</th>
                  <th>Address</th>
                  <th>Current phase</th>
                  <th>Updated</th>
                  <th>Red Field Measure</th>
                  <th>Field Measure Complete</th>
                  <th>Plan</th>
                  <th className="fm-col">Correct</th>
                  <th className="fm-col">Incorrect</th>
                  <th className="fm-col">Super Notified</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <Fragment key={row.job_id}>
                    <tr>
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
                      <td>{row.phase_date ? fmtDate(row.phase_date) : "—"}</td>
                      <td>
                        {row.measure_date ? fmtDate(row.measure_date) : "—"}
                        {row.layout_doc_id && (
                          <>
                            {" "}
                            <button
                              className="link-btn"
                              onClick={() => openDocument(row.layout_doc_id!).catch((e) => setError(e.message))}
                            >
                              layout
                            </button>
                          </>
                        )}
                      </td>
                      <td>
                        {canWrite ? (
                          <input
                            type="date"
                            className="date-input"
                            value={row.fm_complete_date ?? ""}
                            onChange={(e) => setComplete(row, e.target.value).catch((err) => setError(err.message))}
                          />
                        ) : row.fm_complete_date ? (
                          fmtDate(row.fm_complete_date)
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{row.plan ?? "—"}</td>
                      <td className="fm-col">
                        <input
                          type="checkbox"
                          checked={row.fm_correct}
                          disabled={!canWrite}
                          onChange={() => toggleCorrect(row).catch((err) => setError(err.message))}
                        />
                      </td>
                      <td className="fm-col">
                        <input
                          type="checkbox"
                          checked={row.fm_incorrect}
                          disabled={!canWrite}
                          onChange={() => toggleIncorrect(row).catch((err) => setError(err.message))}
                        />
                      </td>
                      <td className="fm-col">
                        <input
                          type="checkbox"
                          checked={row.fm_super_notified}
                          disabled={!canWrite}
                          onChange={() => toggleSuper(row).catch((err) => setError(err.message))}
                        />
                      </td>
                    </tr>
                    {noteFor === row.job_id && (
                      <tr className="fm-note-row">
                        <td colSpan={11}>
                          <div className="fm-note-editor">
                            <label>Field measure issues — Lot {row.lot_number ?? row.job_id}</label>
                            <textarea
                              autoFocus
                              rows={2}
                              placeholder="Describe the measurement issues…"
                              value={noteText}
                              onChange={(e) => setNoteText(e.target.value)}
                            />
                            <div className="fm-note-actions">
                              <button onClick={() => saveNote(row).catch((err) => setError(err.message))}>
                                Save note
                              </button>
                              <button className="link-btn" onClick={() => setNoteFor(null)}>
                                cancel
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={11} className="muted">
                      No active houses in this community.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3 className="kb-head">Field Measure Notes</h3>
          {allNotes.length === 0 ? (
            <p className="muted">No field measure notes yet.</p>
          ) : (
            <ul className="fm-notes-list">
              {allNotes.map((n, i) => (
                <li key={i}>
                  <span className="fm-note-meta">
                    <a href={`#/jobs/${n.row.job_id}`}>
                      Lot {n.row.lot_number ?? n.row.job_code ?? `#${n.row.job_id}`}
                    </a>{" "}
                    · {fmtDate(n.created_at)} · {initials(n.author)}
                  </span>
                  <span className="fm-note-body">{n.body}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
