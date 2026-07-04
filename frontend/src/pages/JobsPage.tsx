import { FormEvent, useEffect, useState } from "react";
import {
  Account,
  Community,
  JOB_STATUSES,
  JobListItem,
  createJob,
  listAccounts,
  listCommunities,
  listJobs,
} from "../api";

export function statusLabel(s: string) {
  return s.replace(/_/g, " ");
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const params: Record<string, string> = {};
    if (statusFilter) params.status_filter = statusFilter;
    if (accountFilter) params.account_id = accountFilter;
    if (search) params.q = search;
    setJobs(await listJobs(params));
  }

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, accountFilter, search]);

  useEffect(() => {
    listAccounts().then(setAccounts).catch(() => {});
  }, []);

  return (
    <div>
      <div className="page-head">
        <h2>Jobs</h2>
        <button onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Close" : "+ New job"}
        </button>
      </div>

      {showCreate && (
        <NewJobForm
          accounts={accounts}
          onCreated={() => {
            setShowCreate(false);
            refresh();
          }}
        />
      )}

      <div className="filters">
        <input
          placeholder="Search address or lot…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {JOB_STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Address</th>
              <th>Account</th>
              <th>Community</th>
              <th>Lot</th>
              <th>Type</th>
              <th>Status</th>
              <th>Install</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="clickable" onClick={() => (window.location.hash = `#/jobs/${j.id}`)}>
                <td>
                  <a href={`#/jobs/${j.id}`}>{j.address}</a>
                </td>
                <td>{j.account_name}</td>
                <td>{j.community_name ?? "—"}</td>
                <td>{j.lot_number ?? "—"}</td>
                <td>{j.job_type}</td>
                <td>
                  <span className={`badge badge-${j.status}`}>{statusLabel(j.status)}</span>
                </td>
                <td>{j.install_date ?? "—"}</td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No jobs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function NewJobForm({ accounts, onCreated }: { accounts: Account[]; onCreated: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({
    account_id: "",
    community_id: "",
    lot_number: "",
    address: "",
    job_type: "tract",
    sales_contact_name: "",
    sales_contact_phone: "",
    sales_contact_email: "",
    field_contact_name: "",
    field_contact_phone: "",
    field_contact_email: "",
  });
  const [communities, setCommunities] = useState<Community[]>([]);
  const [error, setError] = useState("");
  const set = (k: string) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    if (form.account_id) {
      listCommunities(Number(form.account_id)).then(setCommunities).catch(() => {});
    } else {
      setCommunities([]);
    }
  }, [form.account_id]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createJob({
        account_id: Number(form.account_id),
        community_id: form.community_id ? Number(form.community_id) : null,
        lot_number: form.lot_number || null,
        address: form.address,
        job_type: form.job_type,
        sales_contact_name: form.sales_contact_name,
        sales_contact_phone: form.sales_contact_phone || null,
        sales_contact_email: form.sales_contact_email || null,
        field_contact_name: form.field_contact_name,
        field_contact_phone: form.field_contact_phone || null,
        field_contact_email: form.field_contact_email || null,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job");
    }
  }

  return (
    <form className="card form-grid" onSubmit={submit}>
      <label>
        Account
        <select value={form.account_id} onChange={set("account_id")} required>
          <option value="">Select…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Community
        <select value={form.community_id} onChange={set("community_id")}>
          <option value="">None (retail)</option>
          {communities.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Lot #
        <input value={form.lot_number} onChange={set("lot_number")} />
      </label>
      <label>
        Address
        <input value={form.address} onChange={set("address")} required />
      </label>
      <label>
        Job type
        <select value={form.job_type} onChange={set("job_type")}>
          <option value="tract">tract</option>
          <option value="custom">custom</option>
          <option value="remodel">remodel</option>
        </select>
      </label>
      <div className="form-span muted">Sales contact (billing)</div>
      <label>
        Name
        <input value={form.sales_contact_name} onChange={set("sales_contact_name")} required />
      </label>
      <label>
        Phone
        <input value={form.sales_contact_phone} onChange={set("sales_contact_phone")} />
      </label>
      <label>
        Email
        <input type="email" value={form.sales_contact_email} onChange={set("sales_contact_email")} />
      </label>
      <div className="form-span muted">Field contact (measure/install issues)</div>
      <label>
        Name
        <input value={form.field_contact_name} onChange={set("field_contact_name")} required />
      </label>
      <label>
        Phone
        <input value={form.field_contact_phone} onChange={set("field_contact_phone")} />
      </label>
      <label>
        Email
        <input type="email" value={form.field_contact_email} onChange={set("field_contact_email")} />
      </label>
      {error && <p className="error form-span">{error}</p>}
      <div className="form-span">
        <button type="submit">Create job</button>
      </div>
    </form>
  );
}
