/**
 * Walks & Punch on the job page: every post-walk, punch and blue-tape trip on
 * the house with what was found, plus its parts — the same records Autobot
 * writes from the truck.
 */
import { useEffect, useState } from "react";
import { HousePart, WalkVisit, listJobParts, listJobWalks } from "../api";
import { fmtDate } from "../format";
import { FinishForm, PartForm, PartRow, RequestForm } from "./WalkForms";

const TYPE_LABEL: Record<string, string> = { post_walk: "Post walk", punch_out: "Full punch", blue_tape: "Blue tape" };

export default function WalksSection({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [walks, setWalks] = useState<WalkVisit[]>([]);
  const [parts, setParts] = useState<HousePart[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState<{ kind: "finish"; visitId: number; type: string } | { kind: "punch" | "blue" | "part" } | null>(null);

  const load = () =>
    Promise.all([listJobWalks(jobId), listJobParts(jobId)])
      .then(([w, p]) => {
        setWalks(w);
        setParts(p);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
  const done = () => {
    setForm(null);
    load();
  };
  // the part most likely came out of the last walk that happened
  const foundOn = walks.some((w) => w.visit_type === "blue_tape")
    ? "blue_tape"
    : walks.some((w) => w.visit_type === "punch_out" && w.status === "done")
      ? "punch"
      : "post_walk";

  return (
    <>
      <div className="page-head kb-head-row">
        <h3 className="kb-head" style={{ margin: 0 }}>
          Walks &amp; Punch
        </h3>
        {canWrite && (
          <span>
            <button className="secondary small" onClick={() => setForm({ kind: "punch" })}>
              Punch date
            </button>{" "}
            <button className="secondary small" onClick={() => setForm({ kind: "blue" })}>
              Blue tape
            </button>{" "}
            <button className="secondary small" onClick={() => setForm({ kind: "part" })}>
              + Add part
            </button>
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {(form?.kind === "punch" || form?.kind === "blue") && <RequestForm jobId={jobId} kind={form.kind} onDone={done} onCancel={() => setForm(null)} />}
      {form?.kind === "part" && <PartForm jobId={jobId} foundOn={foundOn} onDone={done} onCancel={() => setForm(null)} />}
      {walks.length === 0 ? (
        <p className="muted">No post walk, punch or blue tape on this house yet — they appear once the install date is in and Autobot syncs.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Visit</th>
                <th>Due / scheduled</th>
                <th>Asked / closing</th>
                <th>Done</th>
                <th>Found</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {walks.map((w) => (
                <>
                  <tr key={w.id}>
                    <td>
                      <strong>{TYPE_LABEL[w.visit_type] || w.visit_type}</strong>
                      {w.trip > 1 ? ` · trip ${w.trip}` : ""}
                      <div className="muted">{w.assignee || "Tech"}</div>
                    </td>
                    <td>
                      {w.scheduled_date ? `scheduled ${fmtDate(w.scheduled_date)}` : `due ${fmtDate(w.close_date)}`}
                      {w.status === "pending" && w.close_date && w.close_date < new Date().toISOString().slice(0, 10) ? (
                        <span className="error"> overdue</span>
                      ) : null}
                    </td>
                    <td className="muted">
                      {w.requested_on ? `asked ${fmtDate(w.requested_on)}` : ""}
                      {w.confirmed_with ? ` · ${w.confirmed_with}` : ""}
                      {w.closing_date ? ` · closing ${fmtDate(w.closing_date)}` : ""}
                    </td>
                    <td>
                      {w.status === "done" ? (
                        <>
                          {fmtDate(w.completed_at)}
                          {w.completed_by ? ` · ${w.completed_by}` : ""}
                          {w.result ? <span className="badge"> {w.result.replace("_", " ")}</span> : null}
                        </>
                      ) : (
                        <span className="muted">{w.status}</span>
                      )}
                    </td>
                    <td className="muted">
                      {w.result_notes || w.notes || ""}
                      {w.photos_url ? (
                        <>
                          {" "}
                          <a href={w.photos_url} target="_blank" rel="noreferrer">
                            photos
                          </a>
                        </>
                      ) : null}
                    </td>
                    <td>
                      {canWrite && w.status === "pending" && (
                        <button className="secondary small" onClick={() => setForm({ kind: "finish", visitId: w.id, type: w.visit_type })}>
                          ✓ Finish
                        </button>
                      )}
                    </td>
                  </tr>
                  {form?.kind === "finish" && form.visitId === w.id && (
                    <tr key={`f${w.id}`}>
                      <td colSpan={6}>
                        <FinishForm visitId={w.id} visitType={w.visit_type} onDone={done} onCancel={() => setForm(null)} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h4 style={{ margin: "12px 0 4px" }}>Parts</h4>
      {parts.length === 0 ? (
        <p className="muted">No parts on this house.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Part</th>
                <th className="num">Qty</th>
                <th>Reason</th>
                <th>Found on</th>
                <th>Installs</th>
                <th>Status</th>
                <th>Cost</th>
                <th>Who pays</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {parts.map((p) => (
                <PartRow key={p.id} p={p} canWrite={canWrite} onChange={load} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
