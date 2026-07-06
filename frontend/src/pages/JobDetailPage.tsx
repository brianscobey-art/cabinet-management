import { FormEvent, useEffect, useState } from "react";
import {
  JOB_STATUSES,
  JobDetail,
  addHardware,
  addRoom,
  deleteHardware,
  deleteRoom,
  getJob,
  updateJob,
} from "../api";
import DocumentsSection from "./DocumentsSection";
import { fmtDate, fmtPhone } from "../format";
import { statusLabel } from "./JobsPage";
import QuotesSection from "./QuotesSection";

export default function JobDetailPage({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState("");

  const refresh = () => getJob(jobId).then(setJob).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!job) return <p className="muted">Loading…</p>;

  return (
    <div>
      <p>
        <a href="#/jobs">← Jobs</a>
      </p>
      <div className="page-head">
        <h2>
          {job.job_code ? `${job.job_code} — ` : ""}
          {job.address}
        </h2>
        {canWrite ? (
          <select
            value={job.status}
            onChange={async (e) => {
              await updateJob(job.id, { status: e.target.value });
              refresh();
            }}
          >
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        ) : (
          <span className={`badge badge-${job.status}`}>{statusLabel(job.status)}</span>
        )}
      </div>

      <div className="card-row">
        <div className="card">
          <h3>Job</h3>
          <dl>
            <dt>Job code</dt>
            <dd>{job.job_code ?? "—"}</dd>
            <dt>Account</dt>
            <dd>{job.account_name}</dd>
            <dt>Community / Lot</dt>
            <dd>
              {job.community_name ?? "—"} {job.lot_number ? `/ Lot ${job.lot_number}` : ""}
            </dd>
            <dt>Type</dt>
            <dd>{job.job_type}</dd>
            <dt>Install date</dt>
            <dd>{fmtDate(job.install_date)}</dd>
            <dt>Warranty start</dt>
            <dd>{fmtDate(job.warranty_start_date)}</dd>
          </dl>
        </div>
        <div className="card">
          <h3>Sales contact</h3>
          <dl>
            <dt>Name</dt>
            <dd>{job.sales_contact_name}</dd>
            <dt>Phone</dt>
            <dd>{fmtPhone(job.sales_contact_phone)}</dd>
            <dt>Email</dt>
            <dd>{job.sales_contact_email ?? "—"}</dd>
          </dl>
        </div>
        <div className="card">
          <h3>Field contact</h3>
          <dl>
            <dt>Name</dt>
            <dd>{job.field_contact_name}</dd>
            <dt>Phone</dt>
            <dd>{fmtPhone(job.field_contact_phone)}</dd>
            <dt>Email</dt>
            <dd>{job.field_contact_email ?? "—"}</dd>
          </dl>
        </div>
      </div>

      <h3 className="kb-head">Room selections</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Room</th>
              <th>Zone</th>
              <th>Brand</th>
              <th>Series</th>
              <th>Door style</th>
              <th>Finish</th>
              <th>Species</th>
              {canWrite && <th />}
            </tr>
          </thead>
          <tbody>
            {job.room_selections.map((r) => (
              <tr key={r.id}>
                <td>{r.room}</td>
                <td>{r.zone ? <span className="badge badge-kb">{r.zone}</span> : "—"}</td>
                <td>{r.cabinet_brand ?? "—"}</td>
                <td>{r.series ?? "—"}</td>
                <td>{r.door_style ?? "—"}</td>
                <td>{r.finish ?? "—"}</td>
                <td>{r.wood_species ?? "—"}</td>
                {canWrite && (
                  <td>
                    <button
                      className="link-btn"
                      onClick={async () => {
                        await deleteRoom(r.id);
                        refresh();
                      }}
                    >
                      remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {job.room_selections.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No room selections yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canWrite && <AddRoomForm jobId={job.id} onAdded={refresh} />}

      <h3 className="kb-head">Hardware</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Room</th>
              <th>Type</th>
              <th>Vendor</th>
              <th>Item</th>
              <th>Qty</th>
              {canWrite && <th />}
            </tr>
          </thead>
          <tbody>
            {job.hardware_selections.map((h) => (
              <tr key={h.id}>
                <td>{h.room ?? "—"}</td>
                <td>
                  {h.hardware_type ? (
                    <span className="badge badge-kb">{h.hardware_type} hardware</span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{h.vendor ?? "—"}</td>
                <td>{h.item}</td>
                <td>{h.qty}</td>
                {canWrite && (
                  <td>
                    <button
                      className="link-btn"
                      onClick={async () => {
                        await deleteHardware(h.id);
                        refresh();
                      }}
                    >
                      remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {job.hardware_selections.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No hardware yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canWrite && <AddHardwareForm jobId={job.id} onAdded={refresh} />}

      <DocumentsSection jobId={job.id} canWrite={canWrite} />

      <QuotesSection jobId={job.id} canWrite={canWrite} />
    </div>
  );
}

function AddRoomForm({ jobId, onAdded }: { jobId: number; onAdded: () => void }) {
  const empty = {
    room: "",
    zone: "",
    cabinet_brand: "",
    series: "",
    door_style: "",
    finish: "",
    wood_species: "",
  };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addRoom(jobId, {
        room: form.room,
        zone: form.zone || null,
        cabinet_brand: form.cabinet_brand || null,
        series: form.series || null,
        door_style: form.door_style || null,
        finish: form.finish || null,
        wood_species: form.wood_species || null,
      });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <input placeholder="Room *" value={form.room} onChange={set("room")} required />
      <input placeholder="Zone" value={form.zone} onChange={set("zone")} />
      <input placeholder="Brand" value={form.cabinet_brand} onChange={set("cabinet_brand")} />
      <input placeholder="Series" value={form.series} onChange={set("series")} />
      <input placeholder="Door style" value={form.door_style} onChange={set("door_style")} />
      <input placeholder="Finish" value={form.finish} onChange={set("finish")} />
      <input placeholder="Species" value={form.wood_species} onChange={set("wood_species")} />
      <button type="submit">Add room</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

function AddHardwareForm({ jobId, onAdded }: { jobId: number; onAdded: () => void }) {
  const empty = { room: "", hardware_type: "", vendor: "", item: "", qty: "1" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addHardware(jobId, {
        room: form.room || null,
        hardware_type: form.hardware_type || null,
        vendor: form.vendor || null,
        item: form.item,
        qty: Number(form.qty) || 1,
      });
      setForm(empty);
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <input placeholder="Room" value={form.room} onChange={set("room")} />
      <select value={form.hardware_type} onChange={set("hardware_type")}>
        <option value="">Other hardware</option>
        <option value="door">Door hardware</option>
        <option value="drawer">Drawer hardware</option>
      </select>
      <input placeholder="Vendor" value={form.vendor} onChange={set("vendor")} />
      <input placeholder="Item *" value={form.item} onChange={set("item")} required />
      <input placeholder="Qty" type="number" min="1" value={form.qty} onChange={set("qty")} style={{ width: "4.5rem" }} />
      <button type="submit">Add hardware</button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}
