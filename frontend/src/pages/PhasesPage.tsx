import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Account,
  Community,
  LotNote,
  PhaseBoardRow,
  PhaseDef,
  addFieldMeasureNote,
  addLotNote,
  finishLotNote,
  getLotNotes,
  getPhaseBoard,
  getPhaseDefs,
  listAccounts,
  listCommunities,
  openDocument,
  setJobPhase,
  setPhasesBulk,
  updateFieldMeasure,
} from "../api";
import { fmtDate, fmtLot4 } from "../format";
import PhaseVoicePanel from "./PhaseVoicePanel";

// "Updated" cell color (Alex Talley 10/2/26): yellow once it isn't today's
// check, red once it's more than a week old.
const localDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
function staleClass(iso: string | null): string {
  if (!iso) return "";
  const days = Math.round((localDay(new Date()) - localDay(new Date(iso))) / 86400000);
  return days > 7 ? "updated-old" : days >= 1 ? "updated-stale" : "";
}
// No phase yet, or 0 - Dirt/Staked: hidden unless "Not started" is on (Alex 11/13/26).
const notStarted = (r: PhaseBoardRow) => !r.phase || r.phase === "0";

// "Brian Scobey" -> "BS"
export const initials = (name: string | null | undefined) =>
  (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0]?.toUpperCase())
    .join("") || "—";

// Mirrors FINISHED_PHASES in backend/app/phases.py: from 12 - Cabinets
// Installed on, the house is in close-out.
const CLOSEOUT_PHASES = new Set(["12", "13", "14", "15", "16"]);
const isCloseout = (phase: string | null | undefined) => !!phase && CLOSEOUT_PHASES.has(phase);
type PhaseGroup = "all" | "construction" | "closeout";

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
  // Two halves of the ladder. Construction is everything before the cabinets
  // go in (phases 0-11, and houses with no phase logged yet); Close-out is
  // 12 - Cabinets Installed through 16 - Closed: post walk, punch, blue tape.
  const [group, setGroup] = useState<PhaseGroup>("all");
  const [showNotStarted, setShowNotStarted] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set()); // job_ids checked for a bulk set
  const [bulkPhase, setBulkPhase] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [lotNotes, setLotNotes] = useState<LotNote[]>([]);
  const [lotNoteText, setLotNoteText] = useState("");

  // Phones: let the app header + pickers scroll away so only the phase table's
  // header row stays pinned while someone updates a long list of lots.
  useEffect(() => {
    document.body.classList.add("phases-focus");
    return () => document.body.classList.remove("phases-focus");
  }, []);

  useEffect(() => {
    getPhaseDefs().then(setPhases).catch((e) => setError(e.message));
    // only builders with active (non-closed/void) jobs — no empty names in the picker
    listAccounts(true).then((all) => setBuilders(all.filter((a) => a.type === "builder"))).catch(() => {});
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
    setPicked(new Set());
    setVoiceOpen(false);
    if (communityId) {
      getPhaseBoard(Number(communityId)).then(setRows).catch((e) => setError(e.message));
      getLotNotes(Number(communityId)).then(setLotNotes).catch(() => setLotNotes([]));
    } else {
      setRows([]);
      setLotNotes([]);
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

  // Apply saved phase updates (bulk or voice) to the rows on screen.
  function applySaved(saved: { job_id: number; phase: string; noted_at: string }[]) {
    setRows((rs) =>
      rs.map((r) => {
        const u = saved.find((s) => s.job_id === r.job_id);
        return u
          ? { ...r, phase: u.phase, phase_label: phases.find((p) => p.code === u.phase)?.label ?? u.phase,
              phase_date: u.noted_at }
          : r;
      }),
    );
  }

  async function setPicked_(phase: string) {
    if (!phase || picked.size === 0) return;
    const saved = await setPhasesBulk([...picked].map((job_id) => ({ job_id, phase })));
    applySaved(saved);
    setPicked(new Set());
    setBulkPhase("");
  }

  const togglePick = (jobId: number) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });

  async function addUnknownLot() {
    const body = lotNoteText.trim();
    if (!body || !communityId) return;
    const note = await addLotNote(Number(communityId), body);
    setLotNotes((ns) => [...ns, note]);
    setLotNoteText("");
  }

  async function doneUnknownLot(id: number) {
    await finishLotNote(Number(communityId), id);
    setLotNotes((ns) => ns.filter((n) => n.id !== id));
  }

  // Checking Correct / Incorrect re-confirms the phase server-side (Alex 10/14/26).
  const bumpUpdated = (row: PhaseBoardRow) => (row.phase ? { phase_date: new Date().toISOString() } : {});

  async function toggleCorrect(row: PhaseBoardRow) {
    const next = !row.fm_correct;
    const fm = await updateFieldMeasure(row.job_id, { correct: next });
    patchRow(row.job_id, { fm_correct: fm.correct, fm_incorrect: fm.incorrect, ...(next ? bumpUpdated(row) : {}) });
  }

  async function toggleIncorrect(row: PhaseBoardRow) {
    const next = !row.fm_incorrect;
    const fm = await updateFieldMeasure(row.job_id, { incorrect: next });
    patchRow(row.job_id, { fm_incorrect: fm.incorrect, fm_correct: fm.correct, ...(next ? bumpUpdated(row) : {}) });
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

  const notStartedCount = useMemo(() => rows.filter(notStarted).length, [rows]);
  const startedRows = useMemo(() => (showNotStarted ? rows : rows.filter((r) => !notStarted(r))), [rows, showNotStarted]);
  const closeoutCount = useMemo(() => startedRows.filter((r) => isCloseout(r.phase)).length, [startedRows]);
  const constructionCount = startedRows.length - closeoutCount;
  const shownRows =
    group === "construction" ? startedRows.filter((r) => !isCloseout(r.phase))
    : group === "closeout" ? startedRows.filter((r) => isCloseout(r.phase))
    : startedRows;
  const allPicked = shownRows.length > 0 && shownRows.every((r) => picked.has(r.job_id));
  // Clicking the active button turns the filter off again.
  const pick = (g: PhaseGroup) => setGroup((cur) => (cur === g ? "all" : g));

  // Field measure notes, one block per lot (Brian 10/23/26). Newest note first
  // inside each lot; lots ordered by their newest note. A house marked Correct
  // has its notes archived -- they are hidden here (still on the job page) and
  // come back by themselves if the house is flipped back to Incorrect.
  const noteGroups = rows
    .filter((r) => !r.fm_correct && r.fm_notes.length > 0)
    .map((r) => ({
      row: r,
      notes: [...r.fm_notes].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    }))
    .sort((a, b) => (a.notes[0].created_at < b.notes[0].created_at ? 1 : -1));
  const archivedCount = rows.filter((r) => r.fm_correct && r.fm_notes.length > 0).length;

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
            <>
              <button
                type="button"
                className={group === "construction" ? "toggle-btn on" : "toggle-btn"}
                onClick={() => pick("construction")}
                title="Phases 0 - Dirt/Staked through 11 - Cab Delivered"
              >
                Construction
                <span className="chip-count">{constructionCount}</span>
              </button>
              <button
                type="button"
                className={group === "closeout" ? "toggle-btn on" : "toggle-btn"}
                onClick={() => pick("closeout")}
                title="Phases 12 - Cabinets Installed through 16 - Closed: post walk, punch, blue tape"
              >
                Close Out
                <span className="chip-count">{closeoutCount}</span>
              </button>
              <button
                type="button"
                className={showNotStarted ? "toggle-btn on" : "toggle-btn"}
                onClick={() => setShowNotStarted((v) => !v)}
                title="Houses with no phase yet or 0 - Dirt/Staked. Hidden unless this is on."
              >
                Not started
                <span className="chip-count">{notStartedCount}</span>
              </button>
              {canWrite && (
                <button type="button" className="toggle-btn" onClick={() => setVoiceOpen((v) => !v)}>
                  🎤 Voice
                </button>
              )}
              <span className="muted" style={{ alignSelf: "center" }}>
                {shownRows.length === rows.length
                  ? `${rows.length} active house${rows.length === 1 ? "" : "s"}`
                  : `${shownRows.length} of ${rows.length} active houses`}
              </span>
            </>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {!communityId ? (
        <p className="muted">Pick a builder and community to see its active houses.</p>
      ) : (
        <>
          {voiceOpen && (
            <PhaseVoicePanel
              communityId={Number(communityId)}
              onSaved={applySaved}
              onClose={() => setVoiceOpen(false)}
            />
          )}
          {canWrite && picked.size > 0 && (
            <div className="bulk-bar">
              <b>
                {picked.size} lot{picked.size === 1 ? "" : "s"} checked
              </b>
              <select className="phase-select" value={bulkPhase} onChange={(e) => setBulkPhase(e.target.value)}>
                <option value="">Set them to…</option>
                {phases.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.label}
                  </option>
                ))}
              </select>
              <button
                disabled={!bulkPhase}
                onClick={() => setPicked_(bulkPhase).catch((err) => setError(err.message))}
              >
                Set
              </button>
              <button className="link-btn" onClick={() => setPicked(new Set())}>
                clear
              </button>
            </div>
          )}
          <div className="fm-caption">Field Measure</div>
          <div className="table-wrap">
            <table className="phases-table">
              <thead>
                <tr>
                  {canWrite && (
                    <th className="pick-col">
                      <input
                        type="checkbox"
                        aria-label="Check every lot shown"
                        checked={allPicked}
                        onChange={() =>
                          setPicked(allPicked ? new Set() : new Set(shownRows.map((r) => r.job_id)))
                        }
                      />
                    </th>
                  )}
                  <th>Job code</th>
                  <th>Current phase</th>
                  <th>Updated</th>
                  <th>Plan</th>
                  <th>Lot</th>
                  <th>Address</th>
                  <th>Requested</th>
                  <th className="fm-completed">Completed</th>
                  <th className="fm-col">Correct</th>
                  <th className="fm-col">Incorrect</th>
                  <th className="fm-col">Super Notified</th>
                </tr>
              </thead>
              <tbody>
                {shownRows.map((row) => (
                  <Fragment key={row.job_id}>
                    <tr className={picked.has(row.job_id) ? "picked" : ""}>
                      {canWrite && (
                        <td className="pick-col">
                          <input
                            type="checkbox"
                            aria-label={`Check lot ${row.lot_number ?? row.job_code}`}
                            checked={picked.has(row.job_id)}
                            onChange={() => togglePick(row.job_id)}
                          />
                        </td>
                      )}
                      <td>
                        <a href={`#/jobs/${row.job_id}`}>{row.job_code ?? `#${row.job_id}`}</a>
                      </td>
                      <td>
                        {canWrite ? (
                          // Opens on the current phase so the list starts scrolled
                          // there (Alex 11/25/26); ✓ re-confirms it and bumps Updated.
                          <span className="phase-pick">
                            <select
                              className={`phase-select ${row.phase ? "" : "unset"}`}
                              value={row.phase ?? ""}
                              onChange={(e) => {
                                if (e.target.value)
                                  updatePhase(row, e.target.value).catch((err) => setError(err.message));
                              }}
                            >
                              {!row.phase && <option value="">— set phase —</option>}
                              {phases.map((p) => (
                                <option key={p.code} value={p.code}>
                                  {p.label}
                                </option>
                              ))}
                            </select>
                            {row.phase && (
                              <button
                                type="button"
                                className="same-btn"
                                title="Still at this phase: update the date to today"
                                aria-label="Still at this phase"
                                onClick={() => updatePhase(row, row.phase!).catch((err) => setError(err.message))}
                              >
                                ✓
                              </button>
                            )}
                          </span>
                        ) : (
                          row.phase_label ?? "—"
                        )}
                      </td>
                      <td className={staleClass(row.phase_date)}>{row.phase_date ? fmtDate(row.phase_date) : "—"}</td>
                      <td>{row.plan ?? "—"}</td>
                      <td>{row.lot_number ?? "—"}</td>
                      <td>{row.address}</td>
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
                      <td className="fm-completed">
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
                        <td colSpan={canWrite ? 12 : 11}>
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
                    <td colSpan={canWrite ? 12 : 11} className="muted">
                      No active houses in this community.
                    </td>
                  </tr>
                )}
                {rows.length > 0 && shownRows.length === 0 && (
                  <tr>
                    <td colSpan={canWrite ? 12 : 11} className="muted">
                      Nothing to show with these filters
                      {!showNotStarted && notStartedCount > 0 && ` (${notStartedCount} not started are hidden)`}.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3 className="kb-head">Lots Not in CabinetTron</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Houses seen started in the field that aren't on this list yet (no PO, or not set up). Mark one done once it's
            in CabinetTron.
          </p>
          {lotNotes.length > 0 && (
            <div className="fm-note-groups">
              {lotNotes.map((n) => (
                <div className="fm-note-line lot-note" key={n.id}>
                  <span className="fm-note-meta">
                    {fmtDate(n.created_at)} · {initials(n.author)}
                  </span>
                  <span className="fm-note-body">{n.body}</span>
                  {canWrite && (
                    <button className="link-btn" onClick={() => doneUnknownLot(n.id).catch((e) => setError(e.message))}>
                      done
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {canWrite && (
            <form
              className="lot-note-form"
              onSubmit={(e) => {
                e.preventDefault();
                addUnknownLot().catch((err) => setError(err.message));
              }}
            >
              <input
                value={lotNoteText}
                onChange={(e) => setLotNoteText(e.target.value)}
                placeholder="Lot 23, 141 Liberty Ln: slab poured, no PO"
              />
              <button type="submit" disabled={!lotNoteText.trim()}>
                Add
              </button>
            </form>
          )}

          <h3 className="kb-head">Field Measure Notes</h3>
          {noteGroups.length === 0 ? (
            <p className="muted">No open field measure notes.</p>
          ) : (
            <div className="fm-note-groups">
              {noteGroups.map(({ row, notes }) => (
                <div className="fm-note-group" key={row.job_id}>
                  <div className="fm-note-lot">
                    <a href={`#/jobs/${row.job_id}`}>
                      Lot {row.lot_number ? fmtLot4(row.lot_number) : row.job_code ?? `#${row.job_id}`}
                    </a>{" "}
                    <span className="muted">
                      · {notes.length} note{notes.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  {notes.map((n, i) => (
                    <div className="fm-note-line" key={i}>
                      <span className="fm-note-meta">
                        {fmtDate(n.created_at)} · {initials(n.author)}
                      </span>
                      <span className="fm-note-body">{n.body}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
          {archivedCount > 0 && (
            <p className="muted" style={{ marginTop: "0.4rem" }}>
              Notes for {archivedCount} house{archivedCount === 1 ? "" : "s"} marked Correct are archived (still on each
              job page).
            </p>
          )}
        </>
      )}
    </div>
  );
}
