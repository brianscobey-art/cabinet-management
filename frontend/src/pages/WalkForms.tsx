/**
 * The small forms the punch board and the job page share: finish a visit with
 * what was found, log a punch date from the super, log a blue-tape request,
 * add a part to the house, and move a part along (ordered → received → installed).
 */
import { FormEvent, useState } from "react";
import {
  HousePart,
  addJobPart,
  blueTapeRequest,
  completeVisit,
  patchJobPart,
  punchRequest,
} from "../api";
import { fmtDate } from "../format";

const today = () => new Date().toISOString().slice(0, 10);
const RETURN = ["incomplete", "no_access", "rescheduled"];

const RESULTS: Record<string, [string, string][]> = {
  post_walk: [
    ["ok", "OK — installed right, nothing missing"],
    ["issues", "Issues — damage / missing / not done"],
  ],
  punch_out: [
    ["complete", "Complete"],
    ["incomplete", "Incomplete — coming back"],
    ["no_access", "No access — coming back"],
    ["rescheduled", "Rescheduled"],
  ],
  blue_tape: [
    ["complete", "Complete"],
    ["incomplete", "Incomplete — coming back"],
    ["no_access", "No access — coming back"],
    ["rescheduled", "Rescheduled"],
  ],
};

export const REASONS = ["damaged", "missing", "wrong", "warranty", "other"];
export const WHO_PAYS = ["warranty", "our_error", "installer", "builder", "vendor"];

export function houseStatusClass(st: string): string {
  if (/OVERDUE/.test(st)) return "hs hs-red";
  if (st === "REQUEST PUNCH") return "hs hs-yellow";
  if (/^Blue tape/.test(st) || st === "Waiting on blue tape") return "hs hs-blue";
  if (st === "Done") return "hs hs-green";
  return "hs";
}

export function FinishForm({
  visitId,
  visitType,
  onDone,
  onCancel,
}: {
  visitId: number;
  visitType: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const opts = RESULTS[visitType] || RESULTS.punch_out;
  const [result, setResult] = useState(opts[0][0]);
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState("");
  const [back, setBack] = useState("");
  const [on, setOn] = useState(today());
  const [error, setError] = useState("");
  const needsBack = RETURN.includes(result);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (needsBack && !back) return setError("Pick the day you'll be back");
    try {
      await completeVisit(visitId, {
        result,
        notes: notes.trim() || null,
        photos_url: photos.trim() || null,
        return_date: needsBack ? back : null,
        completed_on: on || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="walk-form" onSubmit={submit}>
      <div className="walk-row">
        <select value={result} onChange={(e) => setResult(e.target.value)}>
          {opts.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        {needsBack && (
          <label>
            back on <input type="date" value={back} onChange={(e) => setBack(e.target.value)} />
          </label>
        )}
        <label>
          done on <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </label>
      </div>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={
          visitType === "post_walk"
            ? "What was damaged, missing or not done — this is the record if there's a claim later"
            : "What was found, what's left"
        }
      />
      <div className="walk-row">
        <input
          value={photos}
          onChange={(e) => setPhotos(e.target.value)}
          placeholder="Photo folder link (OneDrive)"
          style={{ flex: 1, minWidth: 220 }}
        />
        <button type="submit">Save</button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}

export function RequestForm({
  jobId,
  kind,
  onDone,
  onCancel,
}: {
  jobId: number;
  kind: "punch" | "blue";
  onDone: () => void;
  onCancel: () => void;
}) {
  const [on, setOn] = useState(today());
  const [sched, setSched] = useState("");
  const [withWho, setWithWho] = useState("");
  const [closing, setClosing] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      if (kind === "punch")
        await punchRequest(jobId, {
          requested_on: on || null,
          scheduled_date: sched || null,
          confirmed_with: withWho.trim() || null,
          notes: notes.trim() || null,
        });
      else
        await blueTapeRequest(jobId, {
          requested_on: on || null,
          closing_date: closing || null,
          scheduled_date: sched || null,
          notes: notes.trim() || null,
        });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="walk-form" onSubmit={submit}>
      <div className="walk-row">
        <label>
          {kind === "punch" ? "asked the super on" : "super called on"}{" "}
          <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </label>
        {kind === "blue" && (
          <label>
            house closes <input type="date" value={closing} onChange={(e) => setClosing(e.target.value)} />
          </label>
        )}
        <label>
          {kind === "punch" ? "date they gave" : "going on"}{" "}
          <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} />
        </label>
        {kind === "punch" && (
          <input value={withWho} onChange={(e) => setWithWho(e.target.value)} placeholder="confirmed with" />
        )}
      </div>
      <div className="walk-row">
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={kind === "blue" ? "What's on the blue-tape list" : "Notes"}
          style={{ flex: 1, minWidth: 220 }}
        />
        <button type="submit">Save</button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}

export function PartForm({
  jobId,
  foundOn,
  onDone,
  onCancel,
}: {
  jobId: number;
  foundOn: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [part, setPart] = useState("");
  const [cabinet, setCabinet] = useState("");
  const [qty, setQty] = useState(1);
  const [reason, setReason] = useState("damaged");
  const [installBy, setInstallBy] = useState("tech");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!part.trim()) return setError("What part?");
    try {
      await addJobPart(jobId, {
        part: part.trim(),
        cabinet: cabinet.trim() || null,
        qty,
        reason,
        install_by: installBy,
        found_on: foundOn,
        notes: notes.trim() || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="walk-form" onSubmit={submit}>
      <div className="walk-row">
        <input value={part} onChange={(e) => setPart(e.target.value)} placeholder="Part (L-Door, toe kick…)" />
        <input value={cabinet} onChange={(e) => setCabinet(e.target.value)} placeholder="Cabinet (W3636)" style={{ width: 120 }} />
        <input type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value) || 1)} style={{ width: 64 }} />
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {REASONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select value={installBy} onChange={(e) => setInstallBy(e.target.value)}>
          <option value="tech">Tech installs</option>
          <option value="installer">Installer installs</option>
        </select>
      </div>
      <div className="walk-row">
        <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" style={{ flex: 1, minWidth: 220 }} />
        <button type="submit">Add part</button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
        {error && <span className="error">{error}</span>}
      </div>
    </form>
  );
}

/** One part with its next-step buttons. Ordering asks for Everluxe's confirmed
 *  date — the visit is scheduled off that, not the day the order went in. */
export function PartRow({ p, canWrite, onChange }: { p: HousePart; canWrite: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function step(kind: "ordered" | "received" | "installed") {
    let body: Parameters<typeof patchJobPart>[1] = {};
    if (kind === "ordered") {
      const due = window.prompt("Everluxe confirmed date (m/d/yy):", "");
      if (due === null) return;
      const m = due.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
      const iso = m ? `${m[3].length === 2 ? "20" + m[3] : m[3]}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}` : null;
      body = { order_date: today(), due_date: iso };
    } else if (kind === "received") body = { received: true };
    else body = { installed_at: today() };
    setBusy(true);
    try {
      await patchJobPart(p.id, body);
      onChange();
    } finally {
      setBusy(false);
    }
  }
  return (
    <tr>
      <td>
        <strong>{p.part}</strong>
        {p.cabinet ? ` · ${p.cabinet}` : ""}
      </td>
      <td className="num">{p.qty}</td>
      <td>{p.reason ?? ""}</td>
      <td>{p.found_on ? p.found_on.replace("_", " ") : ""}</td>
      <td>{p.install_by === "installer" ? "Installer" : "Tech"}</td>
      <td>
        <span className={p.state === "installed" ? "hs hs-green" : p.state === "needs_order" ? "hs hs-yellow" : "hs"}>
          {p.state.replace("_", " ")}
        </span>
        {p.state === "ordered" && p.due_date ? <span className="muted"> · due {fmtDate(p.due_date)}</span> : ""}
        {p.state === "installed" && p.installed_at ? (
          <span className="muted">
            {" "}
            · {fmtDate(p.installed_at)}
            {p.installed_by ? ` · ${p.installed_by}` : ""}
          </span>
        ) : (
          ""
        )}
      </td>
      <td>{p.cost !== null && p.cost !== undefined ? `$${Number(p.cost).toFixed(2)}` : ""}</td>
      <td>{p.who_pays ? p.who_pays.replace("_", " ") : ""}</td>
      <td>
        {canWrite && !busy && p.state === "needs_order" && (
          <button className="secondary small" onClick={() => step("ordered")}>
            ordered
          </button>
        )}{" "}
        {canWrite && !busy && p.state === "ordered" && (
          <button className="secondary small" onClick={() => step("received")}>
            received
          </button>
        )}{" "}
        {canWrite && !busy && p.state !== "installed" && (
          <button className="secondary small" onClick={() => step("installed")}>
            installed
          </button>
        )}
      </td>
    </tr>
  );
}

export function stepLine(w: { status: string; completed_on: string | null; completed_by: string | null; result: string | null; scheduled_date: string | null; close_date: string | null; overdue: boolean; trip: number } | null) {
  if (!w) return "—";
  if (w.status === "done")
    return `done ${fmtDate(w.completed_on)}${w.completed_by ? ` · ${w.completed_by}` : ""}${w.result ? ` · ${w.result.replace("_", " ")}` : ""}`;
  const when = w.scheduled_date ? `scheduled ${fmtDate(w.scheduled_date)}` : `due ${fmtDate(w.close_date)}`;
  return `${when}${w.trip > 1 ? ` · trip ${w.trip}` : ""}${w.overdue ? " · OVERDUE" : ""}`;
}
