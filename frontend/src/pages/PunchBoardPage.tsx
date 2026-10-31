/**
 * Punch Board — every house past install: where its post walk, full punch and
 * blue tape stand, what parts are open, and what to do next. Reads the same
 * Autobot records the truck writes, so a house is one number everywhere.
 */
import { useEffect, useState } from "react";
import { HousePart, HouseRow, WalkStep, listJobParts, listPunchBoard } from "../api";
import { fmtDate } from "../format";
import { FinishForm, PartForm, PartRow, RequestForm, houseStatusClass, stepLine } from "./WalkForms";

type Filter = "open" | "postwalk" | "request" | "punch" | "blue" | "parts" | "done" | "all";
const FILTERS: [Filter, string][] = [
  ["open", "Open houses"],
  ["postwalk", "Post walks due"],
  ["request", "Ask the super"],
  ["punch", "Punch open"],
  ["blue", "Blue tape open"],
  ["parts", "Parts open"],
  ["done", "Done"],
  ["all", "Everything"],
];

function keep(r: HouseRow, f: Filter): boolean {
  const st = r.house_status;
  switch (f) {
    case "all":
      return true;
    case "open":
      return st !== "Done";
    case "done":
      return st === "Done";
    case "postwalk":
      return /post walk/i.test(st);
    case "request":
      return st === "REQUEST PUNCH";
    case "punch":
      return /punch/i.test(st) && st !== "REQUEST PUNCH";
    case "blue":
      return /blue tape/i.test(st);
    case "parts":
      return r.open_parts > 0;
  }
}

function punchEmail(r: HouseRow): string {
  const subject = encodeURIComponent(`Cabinet punch date — ${r.address}${r.lot_number ? ` (Lot ${r.lot_number})` : ""}`);
  const body = encodeURIComponent(
    `Hi ${r.super_name || ""},\n\nCabinets at ${r.address} were installed ${fmtDate(r.install_date)}. ` +
      `When can we come through for the cabinet punch? A day in the next week or two works for us.\n\nThanks,\nCarter Kitchen & Bath`,
  );
  return `mailto:${r.super_email || ""}?subject=${subject}&body=${body}`;
}

export default function PunchBoardPage({ canWrite }: { canWrite: boolean }) {
  const [rows, setRows] = useState<HouseRow[]>([]);
  const [filter, setFilter] = useState<Filter>("open");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = () =>
    listPunchBoard()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  useEffect(() => {
    load();
  }, []);

  const needle = q.trim().toLowerCase();
  const shown = rows.filter(
    (r) =>
      keep(r, filter) &&
      (!needle ||
        [r.address, r.job_code, r.community, r.builder, r.plan, r.super_name].some((x) =>
          (x || "").toLowerCase().includes(needle),
        )),
  );
  const counts = {
    postwalk: rows.filter((r) => keep(r, "postwalk")).length,
    request: rows.filter((r) => keep(r, "request")).length,
    blue: rows.filter((r) => keep(r, "blue")).length,
    parts: rows.filter((r) => keep(r, "parts")).length,
  };

  return (
    <div>
      <div className="page-head">
        <h2>Punch Board</h2>
        <span className="muted">
          {counts.postwalk} post walks · {counts.request} to ask the super · {counts.blue} blue tape · {counts.parts} with parts open
        </span>
      </div>
      <div className="toolbar" style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          {FILTERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search address, code, community, super…" style={{ minWidth: 280 }} />
        <span className="muted">
          {shown.length} of {rows.length} houses
        </span>
        <button className="secondary" onClick={load}>
          Refresh
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>House</th>
                <th>Builder / community</th>
                <th>Installed</th>
                <th>Status</th>
                <th>Post walk</th>
                <th>Full punch</th>
                <th>Blue tape</th>
                <th className="num">Parts</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <HouseRows key={r.job_id} r={r} open={open === r.job_id} onToggle={() => setOpen(open === r.job_id ? null : r.job_id)} canWrite={canWrite} onChange={load} />
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={9} className="muted">
                    Nothing here.
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

function HouseRows({
  r,
  open,
  onToggle,
  canWrite,
  onChange,
}: {
  r: HouseRow;
  open: boolean;
  onToggle: () => void;
  canWrite: boolean;
  onChange: () => void;
}) {
  return (
    <>
      <tr className="click" onClick={onToggle} style={{ cursor: "pointer" }}>
        <td>
          <strong>{r.address}</strong>
          <div className="muted">
            <a href={`#/jobs/${r.job_id}`} onClick={(e) => e.stopPropagation()}>
              {r.job_code || `job ${r.job_id}`}
            </a>
            {r.plan ? ` · ${r.plan}` : ""}
          </div>
        </td>
        <td>
          {r.builder || ""}
          <div className="muted">
            {r.community || ""}
            {r.super_name ? ` · ${r.super_name}` : ""}
          </div>
        </td>
        <td>{fmtDate(r.install_date)}</td>
        <td>
          <span className={houseStatusClass(r.house_status)}>{r.house_status}</span>
          {r.house_status === "REQUEST PUNCH" && r.super_email && (
            <div>
              <a href={punchEmail(r)} onClick={(e) => e.stopPropagation()}>
                email the super
              </a>
            </div>
          )}
        </td>
        <td className="muted">{stepLine(r.post_walk)}</td>
        <td className="muted">{stepLine(r.punch)}</td>
        <td className="muted">
          {stepLine(r.blue_tape)}
          {r.blue_tape?.closing_date ? <div>closing {fmtDate(r.blue_tape.closing_date)}</div> : null}
        </td>
        <td className="num">{r.open_parts || ""}</td>
        <td className="muted">{open ? "▾" : "▸"}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={9} style={{ background: "var(--bg, #f6faf8)" }}>
            <HouseDetail r={r} canWrite={canWrite} onChange={onChange} />
          </td>
        </tr>
      )}
    </>
  );
}

function StepCard({
  title,
  w,
  children,
}: {
  title: string;
  w: WalkStep | null;
  children?: React.ReactNode;
}) {
  return (
    <div className="step-card">
      <b>{title}</b>
      <div>{stepLine(w)}</div>
      {w?.requested_on && (
        <div className="muted">
          asked {fmtDate(w.requested_on)}
          {w.confirmed_with ? ` · ${w.confirmed_with}` : ""}
        </div>
      )}
      {w?.closing_date && <div className="muted">closing {fmtDate(w.closing_date)}</div>}
      {w?.result_notes && <div className="muted">{w.result_notes}</div>}
      {w?.photos_url && (
        <div>
          <a href={w.photos_url} target="_blank" rel="noreferrer">
            photos
          </a>
        </div>
      )}
      <div style={{ marginTop: 6 }}>{children}</div>
    </div>
  );
}

/** Which walk the part most likely came out of: the last step that has been done. */
function foundOnFor(r: HouseRow): string {
  if (r.blue_tape?.status === "done" || r.blue_tape?.status === "pending") return "blue_tape";
  if (r.punch?.status === "done") return "punch";
  return "post_walk";
}

export function HouseDetail({ r, canWrite, onChange }: { r: HouseRow; canWrite: boolean; onChange: () => void }) {
  const [form, setForm] = useState<{ kind: "finish"; visitId: number; type: string } | { kind: "punch" | "blue" | "part" } | null>(null);
  const [parts, setParts] = useState<HousePart[] | null>(null);
  const loadParts = () => listJobParts(r.job_id).then(setParts).catch(() => setParts([]));
  useEffect(() => {
    loadParts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r.job_id]);
  const done = () => {
    setForm(null);
    onChange();
    loadParts();
  };
  const finish = (w: WalkStep | null, type: string) =>
    canWrite && w && w.status === "pending" ? (
      <button className="secondary small" onClick={() => setForm({ kind: "finish", visitId: w.visit_id, type })}>
        ✓ Finish
      </button>
    ) : null;

  return (
    <div>
      <div className="steps-grid">
        <StepCard title="Post walk" w={r.post_walk}>
          {finish(r.post_walk, "post_walk")}
        </StepCard>
        <StepCard title="Full punch" w={r.punch}>
          {finish(r.punch, "punch_out")}{" "}
          {canWrite && (
            <button className="secondary small" onClick={() => setForm({ kind: "punch" })}>
              Punch date
            </button>
          )}
        </StepCard>
        <StepCard title="Blue tape" w={r.blue_tape}>
          {finish(r.blue_tape, "blue_tape")}{" "}
          {canWrite && (
            <button className="secondary small" onClick={() => setForm({ kind: "blue" })}>
              Blue tape
            </button>
          )}
        </StepCard>
      </div>
      {form?.kind === "finish" && <FinishForm visitId={form.visitId} visitType={form.type} onDone={done} onCancel={() => setForm(null)} />}
      {(form?.kind === "punch" || form?.kind === "blue") && <RequestForm jobId={r.job_id} kind={form.kind} onDone={done} onCancel={() => setForm(null)} />}
      <div className="kb-head-row" style={{ marginTop: 10 }}>
        <h4 style={{ margin: 0 }}>Parts</h4>
        {canWrite && (
          <button className="secondary small" onClick={() => setForm({ kind: "part" })}>
            + Add part
          </button>
        )}
      </div>
      {form?.kind === "part" && <PartForm jobId={r.job_id} foundOn={foundOnFor(r)} onDone={done} onCancel={() => setForm(null)} />}
      {parts && parts.length > 0 ? (
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
                <PartRow key={p.id} p={p} canWrite={canWrite} onChange={done} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No parts on this house.</p>
      )}
      <div className="muted" style={{ marginTop: 6 }}>
        {r.g_code ? `G ${r.g_code}` : ""}
        {r.i_code ? ` · I ${r.i_code}` : ""}
        {r.super_email ? ` · ${r.super_email}` : ""}
      </div>
    </div>
  );
}
