import { FormEvent, useEffect, useState } from "react";
import {
  ServicePart,
  ServiceRequestDetail,
  addServiceLine,
  addServicePart,
  deleteServiceLine,
  deleteServicePart,
  deleteServiceRequest,
  getServiceRequest,
  patchServiceRequest,
} from "../api";
import { fmtDate } from "../format";

const STATUSES = ["open", "scheduled", "complete"];

const partLabel = (p: ServicePart) =>
  `${p.part}${p.cabinet ? ` — ${p.cabinet}` : ""}${p.qty > 1 ? ` ×${p.qty}` : ""}`;

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

  const partById = (id: number | null) => sr.parts.find((p) => p.id === id) || null;

  async function removePart(id: number) {
    await deleteServicePart(id);
    refresh();
  }
  async function removeLine(id: number) {
    await deleteServiceLine(id);
    refresh();
  }
  async function setStatus(status: string) {
    await patchServiceRequest(srId, { status });
    refresh();
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
        <h2>Service Request — {sr.job_code ?? `#${sr.job_id}`}</h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {canWrite ? (
            <select value={sr.status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          ) : (
            <span className="badge">{sr.status}</span>
          )}
          <button onClick={() => window.print()}>🖨 Print</button>
        </div>
      </div>

      {canWrite && (
        <p className="muted no-print" style={{ marginTop: 0 }}>
          <TitleEditor sr={sr} onSaved={refresh} />
        </p>
      )}

      {/* ---------- interactive editor (screen only) ---------- */}
      <div className="no-print">
        <h3 className="kb-head">Parts Needed</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Part</th>
                <th>Cabinet</th>
                <th className="num">Qty</th>
                <th>Notes</th>
                {canWrite && <th />}
              </tr>
            </thead>
            <tbody>
              {sr.parts.map((p) => (
                <tr key={p.id}>
                  <td>{p.part}</td>
                  <td>{p.cabinet ?? "—"}</td>
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
                  <td colSpan={canWrite ? 5 : 4} className="muted">
                    No parts yet — add the parts the tech needs to gather.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {canWrite && <AddPartForm srId={srId} onAdded={refresh} />}

        <h3 className="kb-head">Service / Labor</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Part</th>
                <th>Instruction</th>
                {canWrite && <th />}
              </tr>
            </thead>
            <tbody>
              {sr.lines.map((l, i) => {
                const p = partById(l.part_id);
                return (
                  <tr key={l.id}>
                    <td>{i + 1}</td>
                    <td>{p ? partLabel(p) : <span className="muted">general</span>}</td>
                    <td>{l.instruction}</td>
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
                  <td colSpan={canWrite ? 4 : 3} className="muted">
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

      {/* ---------- clean print form ---------- */}
      <ServiceRequestPrint sr={sr} />
    </div>
  );
}

function ServiceRequestPrint({ sr }: { sr: ServiceRequestDetail }) {
  const partById = (id: number | null) => sr.parts.find((p) => p.id === id) || null;
  return (
    <div className="print-only service-print">
      <div className="print-title">Service Request — {sr.job_code ?? `#${sr.job_id}`}</div>
      <div className="service-sub">
        {sr.address}
        {sr.community_name ? ` · ${sr.community_name}` : ""}
        {sr.lot_number ? ` · Lot ${sr.lot_number}` : ""} · {fmtDate(sr.created_at)}
        {sr.title ? ` · ${sr.title}` : ""}
      </div>

      <h3 className="service-print-head">Parts Needed</h3>
      <table className="service-print-table">
        <thead>
          <tr>
            <th style={{ width: "2rem" }}></th>
            <th>Part</th>
            <th>Cabinet</th>
            <th className="num">Qty</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {sr.parts.map((p) => (
            <tr key={p.id}>
              <td>☐</td>
              <td>{p.part}</td>
              <td>{p.cabinet ?? ""}</td>
              <td className="num">{p.qty}</td>
              <td>{p.notes ?? ""}</td>
            </tr>
          ))}
          {sr.parts.length === 0 && (
            <tr>
              <td colSpan={5}>—</td>
            </tr>
          )}
        </tbody>
      </table>

      <h3 className="service-print-head">Service</h3>
      <ol className="service-print-lines">
        {sr.lines.map((l) => {
          const p = partById(l.part_id);
          return (
            <li key={l.id}>
              {p && <strong>[{partLabel(p)}] </strong>}
              {l.instruction}
            </li>
          );
        })}
        {sr.lines.length === 0 && <li>—</li>}
      </ol>
    </div>
  );
}

function TitleEditor({ sr, onSaved }: { sr: ServiceRequestDetail; onSaved: () => void }) {
  const [title, setTitle] = useState(sr.title ?? "");
  return (
    <input
      className="service-title-input"
      placeholder="Title (e.g. Punch list — master bath)"
      value={title}
      onChange={(e) => setTitle(e.target.value)}
      onBlur={() => {
        if ((sr.title ?? "") !== title) patchServiceRequest(sr.id, { title: title || null }).then(onSaved);
      }}
    />
  );
}

function AddPartForm({ srId, onAdded }: { srId: number; onAdded: () => void }) {
  const empty = { part: "", cabinet: "", qty: "1", notes: "" };
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
      await addServiceLine(srId, {
        part_id: partId ? Number(partId) : null,
        instruction,
      });
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
        {parts.map((p) => (
          <option key={p.id} value={p.id}>
            {partLabel(p)}
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
