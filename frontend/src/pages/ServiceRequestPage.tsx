import { FormEvent, useEffect, useState } from "react";
import {
  ServiceLine,
  ServicePart,
  ServiceRequestDetail,
  addServiceLine,
  addServicePart,
  deleteServiceLine,
  deleteServicePart,
  deleteServiceRequest,
  getServiceRequest,
  patchServiceLine,
  patchServiceRequest,
} from "../api";
import { fmtDate } from "../format";
import { initials } from "./PhasesPage";

const STATUSES = ["Installed", "Warranty", "Service Empty", "Service Occupied"];
const MATERIAL_STATUSES = ["Not Ordered", "Ordered", "Received", "N/A"];
const BLANK_PART_ROWS = 3;
const BLANK_SERVICE_ROWS = 3;

const partLabel = (p: ServicePart) => `${p.part}${p.cabinet ? ` — ${p.cabinet}` : ""}`;

export default function ServiceRequestPage({ srId, canWrite }: { srId: number; canWrite: boolean }) {
  const [sr, setSr] = useState<ServiceRequestDetail | null>(null);
  const [error, setError] = useState("");

  const refresh = () => getServiceRequest(srId).then(setSr).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srId]);

  if (error) return <p className="error">{error}</p>;
  if (!sr) return <p className="muted">Loading…</p>;

  const partNumber = (id: number | null) => {
    if (id == null) return null;
    const i = sr.parts.findIndex((p) => p.id === id);
    return i >= 0 ? i + 1 : null;
  };
  const partById = (id: number | null) => sr.parts.find((p) => p.id === id) || null;

  async function removePart(id: number) {
    await deleteServicePart(id);
    refresh();
  }
  async function removeLine(id: number) {
    await deleteServiceLine(id);
    refresh();
  }
  async function toggleDone(l: ServiceLine) {
    await patchServiceLine(l.id, { done: !l.done });
    refresh();
  }
  async function saveNote(l: ServiceLine, note: string) {
    if ((l.note ?? "") === note) return;
    await patchServiceLine(l.id, { note });
    refresh();
  }
  async function setStatus(status: string) {
    await patchServiceRequest(srId, { status });
    refresh();
  }

  // Print names the document (PDF filename + header): "Service Request CODE Builder MMDDYY"
  function printReport() {
    const d = new Date();
    const mmddyy =
      String(d.getMonth() + 1).padStart(2, "0") +
      String(d.getDate()).padStart(2, "0") +
      String(d.getFullYear()).slice(2);
    const name = ["Service Request", sr!.job_code, sr!.account_name, mmddyy].filter(Boolean).join(" ");
    const prev = document.title;
    document.title = name;
    const restore = () => {
      document.title = prev;
      window.removeEventListener("afterprint", restore);
    };
    window.addEventListener("afterprint", restore);
    window.print();
  }

  return (
    <div className="service-page">
      <p className="back-row no-print">
        <a href={`#/jobs/${sr.job_id}`}>← Job {sr.job_code ?? `#${sr.job_id}`}</a>
        <button className="back-btn" onClick={() => window.history.back()}>
          ← Back
        </button>
      </p>

      <div className="page-head no-print">
        <h2>Service Report — {sr.job_code ?? `#${sr.job_id}`}</h2>
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          {canWrite ? (
            <select value={sr.status} onChange={(e) => setStatus(e.target.value)}>
              {!STATUSES.includes(sr.status) && <option value={sr.status}>{sr.status}</option>}
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          ) : (
            <span className="badge">{sr.status}</span>
          )}
          <button onClick={printReport}>🖨 Print</button>
          <span className="brand-tag">Carter Kitchen and Bath</span>
        </div>
      </div>

      {canWrite && (
        <div className="no-print service-meta">
          <TitleEditor sr={sr} onSaved={refresh} />
          <label>
            Material
            <select
              value={sr.material_status ?? ""}
              onChange={async (e) => {
                await patchServiceRequest(srId, { material_status: e.target.value || null });
                refresh();
              }}
            >
              <option value="">Material status…</option>
              {MATERIAL_STATUSES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label>
            Scheduled
            <input
              type="date"
              className="date-input"
              value={sr.scheduled_date ?? ""}
              onChange={async (e) => {
                await patchServiceRequest(srId, { scheduled_date: e.target.value || null });
                refresh();
              }}
            />
          </label>
        </div>
      )}

      {/* ---------- interactive service report (screen only) ---------- */}
      <div className="no-print">
        <h3 className="kb-head">
          Cabinet &amp; Hardware <span className="muted-sm">from job file</span>
        </h3>
        <div className="combo-grid">
          <div className="table-wrap">
            <table className="condensed">
              <thead>
                <tr>
                  <th>Room / Zone</th>
                  <th>Vendor</th>
                  <th>Series</th>
                  <th>Door style</th>
                  <th>Color</th>
                  <th>Species</th>
                </tr>
              </thead>
              <tbody>
                {sr.rooms.map((r) => (
                  <tr key={r.id}>
                    <td>{r.room}{r.zone ? ` / ${r.zone}` : ""}</td>
                    <td>{r.cabinet_brand ?? "—"}</td>
                    <td>{r.series ?? "—"}</td>
                    <td>{r.door_style ?? "—"}</td>
                    <td>{r.finish ?? "—"}</td>
                    <td>{r.wood_species ?? "—"}</td>
                  </tr>
                ))}
                {sr.rooms.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">No cabinet selections on this job.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table className="condensed">
              <thead>
                <tr>
                  <th>Hardware type</th>
                </tr>
              </thead>
              <tbody>
                {sr.hardware.map((h) => (
                  <tr key={h.id}>
                    <td>{h.hardware_type ?? "—"}</td>
                  </tr>
                ))}
                {sr.hardware.length === 0 && (
                  <tr>
                    <td className="muted">No hardware on this job.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <h3 className="kb-head">Parts Needed</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>Part</th>
                <th>Cabinet</th>
                <th>Style</th>
                <th>Color</th>
                <th>Vendor</th>
                <th>Order #</th>
                <th>Order Date</th>
                <th>Due Date</th>
                <th className="num">Qty</th>
                <th>Notes</th>
                {canWrite && <th />}
              </tr>
            </thead>
            <tbody>
              {sr.parts.map((p, i) => (
                <tr key={p.id}>
                  <td className="num">{i + 1}</td>
                  <td>{p.part}</td>
                  <td>{p.cabinet ?? "—"}</td>
                  <td>{p.style ?? "—"}</td>
                  <td>{p.color ?? "—"}</td>
                  <td>{p.vendor ?? "—"}</td>
                  <td>{p.order_number ?? "—"}</td>
                  <td>{p.order_date ? fmtDate(p.order_date) : "—"}</td>
                  <td>{p.due_date ? fmtDate(p.due_date) : "—"}</td>
                  <td className="num">{p.qty}</td>
                  <td>{p.notes ?? "—"}</td>
                  {canWrite && (
                    <td>
                      <button className="link-btn" onClick={() => removePart(p.id).catch((e) => setError(e.message))}>
                        remove
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {sr.parts.length === 0 && (
                <tr>
                  <td colSpan={canWrite ? 12 : 11} className="muted">
                    No parts yet — add the parts the tech needs to gather.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {canWrite && <AddPartForm srId={srId} onAdded={refresh} />}

        <h3 className="kb-head">Service Needed</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="fm-col">Done</th>
                <th className="num">Part #</th>
                <th>Cabinet</th>
                <th>Description of work</th>
                <th>Tech note</th>
                <th>Tech / Date</th>
                {canWrite && <th />}
              </tr>
            </thead>
            <tbody>
              {sr.lines.map((l) => {
                const p = partById(l.part_id);
                return (
                  <tr key={l.id} className={l.done ? "line-done" : ""}>
                    <td className="fm-col">
                      <input
                        type="checkbox"
                        checked={l.done}
                        disabled={!canWrite}
                        onChange={() => toggleDone(l).catch((e) => setError(e.message))}
                      />
                    </td>
                    <td className="num">{partNumber(l.part_id) ?? "—"}</td>
                    <td>{p?.cabinet ?? "—"}</td>
                    <td>{l.instruction}</td>
                    <td>
                      {canWrite ? (
                        <input
                          className="line-note-input"
                          defaultValue={l.note ?? ""}
                          placeholder="add note…"
                          onBlur={(e) => saveNote(l, e.target.value).catch((err) => setError(err.message))}
                        />
                      ) : (
                        l.note ?? ""
                      )}
                    </td>
                    <td className="muted">
                      {l.done ? `${initials(l.done_by)}${l.done_at ? ` · ${fmtDate(l.done_at)}` : ""}` : ""}
                    </td>
                    {canWrite && (
                      <td>
                        <button className="link-btn" onClick={() => removeLine(l.id).catch((e) => setError(e.message))}>
                          remove
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
              {sr.lines.length === 0 && (
                <tr>
                  <td colSpan={canWrite ? 7 : 6} className="muted">
                    No service lines yet — add what to do with each part.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {canWrite && <AddLineForm srId={srId} parts={sr.parts} onAdded={refresh} />}

        {canWrite && (
          <p style={{ marginTop: "1.5rem" }}>
            <button
              className="link-btn danger"
              onClick={async () => {
                if (confirm("Delete this entire service request?")) {
                  await deleteServiceRequest(srId);
                  window.location.hash = `#/jobs/${sr.job_id}`;
                }
              }}
            >
              delete service request
            </button>
          </p>
        )}
      </div>

      {/* ---------- printed QC-style service report ---------- */}
      <ServiceReportPrint sr={sr} partNumber={partNumber} partById={partById} />
    </div>
  );
}

function blanks(n: number, cols: number) {
  return Array.from({ length: n }, (_, i) => (
    <tr key={`b${i}`} className="qc-blank">
      {Array.from({ length: cols }, (_, c) => (
        <td key={c}>&nbsp;</td>
      ))}
    </tr>
  ));
}

export function ServiceReportPrint({
  sr,
  partNumber,
  partById,
  blank = false,
  screen = false,
}: {
  sr: ServiceRequestDetail;
  partNumber: (id: number | null) => number | null;
  partById: (id: number | null) => ServicePart | null;
  blank?: boolean;
  screen?: boolean;
}) {
  const partBlanks = BLANK_PART_ROWS;
  const svcBlanks = BLANK_SERVICE_ROWS;
  return (
    <div className={`${screen ? "" : "print-only "}qc-report`}>
      <div className="qc-header">
        <div className="qc-title">SERVICE REQUEST</div>
        <div className="qc-brand">
          <img src="/carter-logo.png" alt="Carter Lumber" className="qc-logo" />
          <span className="qc-brand-name">Carter Kitchen and Bath</span>
        </div>
      </div>

      <table className="qc-info">
        <tbody>
          <tr>
            <th>PROJECT</th>
            <td>{sr.community_name ?? ""}</td>
            <th>ADDRESS</th>
            <td>{sr.address}</td>
            <th>LOT</th>
            <td>{sr.lot_number ?? ""}</td>
          </tr>
          <tr>
            <th>JOB CODE</th>
            <td>{sr.job_code ?? ""}</td>
            <th>DATE</th>
            <td>{blank ? "" : fmtDate(sr.created_at)}</td>
            <th>STATUS</th>
            <td>{blank ? "" : sr.status}</td>
          </tr>
        </tbody>
      </table>

      <div className="qc-bar">CABINET SPECIFICATIONS &amp; HARDWARE</div>
      <div className="qc-combo">
        <table className="qc-table">
          <thead>
            <tr>
              <th>Room / Zone</th>
              <th>Vendor</th>
              <th>Series</th>
              <th>Door Style</th>
              <th>Color</th>
              <th>Species</th>
            </tr>
          </thead>
          <tbody>
            {sr.rooms.map((r) => (
              <tr key={r.id}>
                <td>{r.room}{r.zone ? ` / ${r.zone}` : ""}</td>
                <td>{r.cabinet_brand ?? ""}</td>
                <td>{r.series ?? ""}</td>
                <td>{r.door_style ?? ""}</td>
                <td>{r.finish ?? ""}</td>
                <td>{r.wood_species ?? ""}</td>
              </tr>
            ))}
            {sr.rooms.length === 0 && blanks(1, 6)}
          </tbody>
        </table>
        <table className="qc-table">
          <thead>
            <tr>
              <th>Hardware Type</th>
            </tr>
          </thead>
          <tbody>
            {sr.hardware.map((h) => (
              <tr key={h.id}>
                <td>{h.hardware_type ?? ""}</td>
              </tr>
            ))}
            {sr.hardware.length === 0 && blanks(1, 1)}
          </tbody>
        </table>
      </div>

      <div className="qc-bar">PARTS NEEDED</div>
      <table className="qc-table qc-parts">
        <thead>
          <tr>
            <th className="num" style={{ width: "2.4rem" }}>Item #</th>
            <th className="num" style={{ width: "2.2rem" }}>Qty</th>
            <th>Part</th>
            <th>Cabinet</th>
            <th>Style</th>
            <th>Color</th>
            <th>Vendor</th>
            <th className="ctr">Order #</th>
            <th className="ctr">Order Date</th>
            <th className="ctr">Due Date</th>
            <th>Notes</th>
            <th style={{ width: "2rem" }}>✓</th>
          </tr>
        </thead>
        <tbody>
          {sr.parts.map((p, i) => (
            <tr key={p.id}>
              <td className="num">{i + 1}</td>
              <td className="num">{p.qty}</td>
              <td>{p.part}</td>
              <td>{p.cabinet ?? ""}</td>
              <td>{p.style ?? ""}</td>
              <td>{p.color ?? ""}</td>
              <td>{p.vendor ?? ""}</td>
              <td className="ctr">{p.order_number ?? ""}</td>
              <td className="ctr">{p.order_date ? fmtDate(p.order_date) : ""}</td>
              <td className="ctr">{p.due_date ? fmtDate(p.due_date) : ""}</td>
              <td>{p.notes ?? ""}</td>
              <td className="qc-check">☐</td>
            </tr>
          ))}
          {blanks(partBlanks, 12)}
        </tbody>
      </table>

      <div className="qc-bar">SERVICE NEEDED</div>
      <table className="qc-table">
        <thead>
          <tr>
            <th className="num" style={{ width: "3rem" }}>Part #</th>
            <th>Cabinet</th>
            <th>Description of Work</th>
            <th style={{ width: "2.5rem" }}>✓</th>
            <th className="ctr" style={{ width: "5rem" }}>Date</th>
            <th style={{ width: "4rem" }}>Tech</th>
          </tr>
        </thead>
        <tbody>
          {sr.lines.map((l) => {
            const p = partById(l.part_id);
            return (
              <tr key={l.id}>
                <td className="num">{partNumber(l.part_id) ?? ""}</td>
                <td>{p?.cabinet ?? ""}</td>
                <td>
                  {l.instruction}
                  {l.note ? ` — ${l.note}` : ""}
                </td>
                <td className="qc-check">{l.done ? "☑" : "☐"}</td>
                <td className="ctr">{l.done_at ? fmtDate(l.done_at) : ""}</td>
                <td>{l.done ? initials(l.done_by) : ""}</td>
              </tr>
            );
          })}
          {blanks(svcBlanks, 6)}
        </tbody>
      </table>

      <div className="qc-signoff qc-sign-row">
        <div className="qc-sign qc-sign-sig">
          <div className="qc-sign-blank" />
          <div className="qc-sign-label">Service Tech — Signature</div>
        </div>
        <div className="qc-sign qc-sign-date">
          <div className="qc-sign-blank" />
          <div className="qc-sign-label">Date</div>
        </div>
        <div className="qc-sign qc-sign-sig">
          <div className="qc-sign-blank" />
          <div className="qc-sign-label">Customer — Signature</div>
        </div>
        <div className="qc-sign qc-sign-date">
          <div className="qc-sign-blank" />
          <div className="qc-sign-label">Date</div>
        </div>
      </div>

      <div className="qc-footer">
        {["Service Request", sr.job_code, sr.account_name].filter(Boolean).join(" · ")} ·{" "}
        {new Date().toLocaleString("en-US", {
          month: "numeric",
          day: "numeric",
          year: "2-digit",
          hour: "numeric",
          minute: "2-digit",
        })}
      </div>
    </div>
  );
}

function TitleEditor({ sr, onSaved }: { sr: ServiceRequestDetail; onSaved: () => void }) {
  const [title, setTitle] = useState(sr.title ?? "");
  return (
    <input
      className="service-title-input"
      placeholder="Title (e.g. Punch list - master bath)"
      value={title}
      onChange={(e) => setTitle(e.target.value)}
      onBlur={() => {
        if ((sr.title ?? "") !== title) patchServiceRequest(sr.id, { title: title || null }).then(onSaved);
      }}
    />
  );
}

function AddPartForm({ srId, onAdded }: { srId: number; onAdded: () => void }) {
  const empty = {
    part: "", cabinet: "", style: "", color: "", vendor: "",
    order_number: "", order_date: "", due_date: "", qty: "1", notes: "",
  };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addServicePart(srId, {
        part: form.part,
        cabinet: form.cabinet || null,
        style: form.style || null,
        color: form.color || null,
        vendor: form.vendor || null,
        order_number: form.order_number || null,
        order_date: form.order_date || null,
        due_date: form.due_date || null,
        qty: Number(form.qty) || 1,
        notes: form.notes || null,
      });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <input placeholder="Part * (e.g. L-Door)" value={form.part} onChange={set("part")} required />
      <input placeholder="Cabinet (e.g. W3636)" value={form.cabinet} onChange={set("cabinet")} />
      <input placeholder="Style" value={form.style} onChange={set("style")} />
      <input placeholder="Color" value={form.color} onChange={set("color")} />
      <input placeholder="Vendor" value={form.vendor} onChange={set("vendor")} />
      <input placeholder="Order #" value={form.order_number} onChange={set("order_number")} style={{ width: "7rem" }} />
      <label className="inline-date" title="Order date">
        Ord<input type="date" value={form.order_date} onChange={set("order_date")} />
      </label>
      <label className="inline-date" title="Due date">
        Due<input type="date" value={form.due_date} onChange={set("due_date")} />
      </label>
      <input placeholder="Qty" type="number" min="1" value={form.qty} onChange={set("qty")} style={{ width: "4.5rem" }} />
      <input placeholder="Notes" value={form.notes} onChange={set("notes")} />
      <button type="submit">Add part</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function AddLineForm({ srId, parts, onAdded }: { srId: number; parts: ServicePart[]; onAdded: () => void }) {
  const [partId, setPartId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addServiceLine(srId, { part_id: partId ? Number(partId) : null, instruction });
      setInstruction("");
      setPartId("");
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <select value={partId} onChange={(e) => setPartId(e.target.value)}>
        <option value="">— no part —</option>
        {parts.map((p, i) => (
          <option key={p.id} value={p.id}>
            {i + 1}. {partLabel(p)}
          </option>
        ))}
      </select>
      <input
        placeholder="Instruction * (e.g. Replace L-door on W3636 left of window)"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        required
        style={{ flex: 1, minWidth: "18rem" }}
      />
      <button type="submit">Add line</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}
