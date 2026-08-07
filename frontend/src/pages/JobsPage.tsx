import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Account,
  Community,
  JOB_STATUSES,
  JobListItem,
  statusSlug,
  createJob,
  listAccounts,
  listAllCommunities,
  listCommunities,
  listJobs,
} from "../api";
import { fmtDate } from "../format";

export function statusLabel(s: string) {
  return s; // status values are already display-ready (1.0-Track ... 8.0-Void)
}

// A pop-open dropdown of checkboxes — closes on outside click. Empty selection
// means "all"; the button shows the current summary.
function MultiSelectDropdown({
  options,
  selected,
  onChange,
  allLabel,
}: {
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
  allLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const summary =
    selected.length === 0
      ? allLabel
      : selected.length === 1
      ? options.find((o) => o.value === selected[0])?.label ?? "1 selected"
      : `${selected.length} selected`;
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  return (
    <div className="ms" ref={ref}>
      <button type="button" className="ms-btn" onClick={() => setOpen((o) => !o)}>
        <span className="ms-summary">{summary}</span>
        <span className="ms-caret">▾</span>
      </button>
      {open && (
        <div className="ms-menu">
          <label className="ms-opt">
            <input type="checkbox" checked={selected.length === 0} onChange={() => onChange([])} />
            {allLabel}
          </label>
          {options.map((o) => (
            <label key={o.value} className="ms-opt">
              <input
                type="checkbox"
                checked={selected.includes(o.value)}
                onChange={() => toggle(o.value)}
              />
              {o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

const isNational = (a: Account) =>
  a.type === "builder" && (a.name.startsWith("DR Horton") || a.name.startsWith("Century"));

type Category = "" | "local" | "dr_horton" | "century" | "national_other";

const CATEGORY_LABELS: Record<Exclude<Category, "">, string> = {
  dr_horton: "DR Horton",
  century: "Century",
  national_other: "Other National",
  local: "Local",
};

function accountInCategory(a: Account, category: Category): boolean {
  if (category === "dr_horton") return a.name.startsWith("DR Horton");
  if (category === "century") return a.name.startsWith("Century");
  if (category === "national_other") return isNational(a) && !a.name.startsWith("DR Horton") && !a.name.startsWith("Century");
  return !isNational(a); // local
}

// Remember where the user was in the Jobs chooser so the browser Back button
// (from a job detail page) returns to the same community view, not the top.
export const NAV_KEY = "jobsNav";
function savedNav(): Partial<Record<string, string | boolean>> {
  try {
    return JSON.parse(sessionStorage.getItem(NAV_KEY) || "{}");
  } catch {
    return {};
  }
}

export default function JobsPage({ archived = false }: { archived?: boolean }) {
  const nav = archived ? {} : savedNav();
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [category, setCategory] = useState<Category>((nav.category as Category) || "");
  const [nationalStep, setNationalStep] = useState(Boolean(nav.nationalStep));
  const [communityChosen, setCommunityChosen] = useState(Boolean(nav.communityChosen));
  const [allCommunities, setAllCommunities] = useState<Community[]>([]);
  const [statusFilter, setStatusFilter] = useState((nav.statusFilter as string) || "");
  const [accountFilter, setAccountFilter] = useState((nav.accountFilter as string) || "");
  // several communities can be selected at once
  const [communityIds, setCommunityIds] = useState<string[]>(
    Array.isArray(nav.communityIds) ? (nav.communityIds as string[]) : []
  );
  const [search, setSearch] = useState((nav.search as string) || "");
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");

  // Persist the chooser/filter state on every change (active Jobs view only).
  useEffect(() => {
    if (archived) return;
    sessionStorage.setItem(
      NAV_KEY,
      JSON.stringify({ category, nationalStep, communityChosen, statusFilter, accountFilter, communityIds, search })
    );
  }, [archived, category, nationalStep, communityChosen, statusFilter, accountFilter, communityIds, search]);

  async function refresh() {
    const params: Record<string, string | string[]> = {};
    if (archived) params.archived = "true";
    else if (statusFilter) params.status_filter = statusFilter;
    if (!archived && category) params.category = category;
    if (accountFilter) params.account_id = accountFilter;
    if (communityIds.length) params.community_ids = communityIds;
    if (search) params.q = search;
    setJobs(await listJobs(params));
  }

  useEffect(() => {
    if (!archived && !category) return; // waiting on the National/Local choice
    if (!archived && category !== "local" && !communityChosen) return; // waiting on community choice
    refresh().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, accountFilter, communityIds, search, archived, category, communityChosen]);

  useEffect(() => {
    if (!archived) listAllCommunities().then(setAllCommunities).catch(() => {});
  }, [archived]);

  useEffect(() => {
    listAccounts().then(setAccounts).catch(() => {});
  }, []);


  // Jobs opens with a National/Local choice; National drills into a builder choice.
  if (!archived && !category) {
    return (
      <div className="center-page">
        {!nationalStep ? (
          <>
            <h2>Which jobs?</h2>
            <div className="category-choice">
              <button className="category-card" onClick={() => setNationalStep(true)}>
                <span className="category-title">National Accounts</span>
                <span className="muted">DR Horton, Century &amp; more</span>
              </button>
              <button
                className="category-card"
                onClick={() => {
                  setCategory("local");
                  setCommunityChosen(true);
                }}
              >
                <span className="category-title">Local Accounts</span>
                <span className="muted">Local builders &amp; retail customers</span>
              </button>
            </div>
          </>
        ) : (
          <>
            <h2>Which national builder?</h2>
            <div className="category-choice">
              <button className="category-card" onClick={() => setCategory("dr_horton")}>
                <span className="category-title">DR Horton</span>
                <span className="muted">All five divisions</span>
              </button>
              <button className="category-card" onClick={() => setCategory("century")}>
                <span className="category-title">Century</span>
                <span className="muted">Century Complete</span>
              </button>
              <button className="category-card" onClick={() => setCategory("national_other")}>
                <span className="category-title">Other</span>
                <span className="muted">Future national builders</span>
              </button>
            </div>
            <button className="link-btn" onClick={() => setNationalStep(false)}>
              ← back
            </button>
          </>
        )}
      </div>
    );
  }

  const categoryAccounts = accounts.filter((a) => accountInCategory(a, category));
  // DR Horton is one builder split into divisions (its per-division accounts).
  const isDrh = category === "dr_horton";
  const divisionLabel = (name: string) => name.replace(/^DR Horton\s*/, "") || name;
  // communities to offer in the multi-select: for the chosen division, or across
  // every account in the current builder/category when no single division is set.
  const scopeAccountIds = accountFilter
    ? [Number(accountFilter)]
    : (archived ? accounts : categoryAccounts).map((a) => a.id);
  const communityOptions = allCommunities
    .filter((c) => scopeAccountIds.includes(c.account_id))
    .sort((a, b) => a.name.localeCompare(b.name));

  // National flow: after the builder, pick a community (or all of them).
  if (!archived && category && category !== "local" && !communityChosen) {
    const accountById = new Map(categoryAccounts.map((a) => [a.id, a]));
    const communities = allCommunities
      .filter((c) => accountById.has(c.account_id))
      .sort((a, b) =>
        (accountById.get(a.account_id)!.name + a.name).localeCompare(accountById.get(b.account_id)!.name + b.name)
      );
    return (
      <div className="center-page">
        <h2>{CATEGORY_LABELS[category]} — which community?</h2>
        <div className="category-choice community-grid">
          <button
            className="category-card"
            onClick={() => {
              setAccountFilter("");
              setCommunityIds([]);
              setCommunityChosen(true);
            }}
          >
            <span className="category-title">All Communities</span>
            <span className="muted">everything for {CATEGORY_LABELS[category]}</span>
          </button>
          {communities.map((c) => (
            <button
              key={c.id}
              className="category-card"
              onClick={() => {
                setAccountFilter(String(c.account_id));
                setCommunityIds([String(c.id)]);
                setCommunityChosen(true);
              }}
            >
              <span className="category-title">{c.name}</span>
              <span className="muted">{accountById.get(c.account_id)!.name}</span>
            </button>
          ))}
        </div>
        {communities.length === 0 && <p className="muted">No communities in this group yet.</p>}
        <button
          className="link-btn"
          onClick={() => {
            setCategory("");
            setNationalStep(true);
          }}
        >
          ← back
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="page-sticky">
      <div className="page-head">
        <h2>{archived ? "Archive — closed & void jobs" : `Jobs — ${category ? CATEGORY_LABELS[category] : ""}`}</h2>
        {!archived && (
          <button onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Close" : "+ New job"}
          </button>
        )}
      </div>

      <div className="filters">
        {!archived && (
          <>
            {category !== "local" && (
              <div className="view-toggle">
                {(["dr_horton", "century", "national_other"] as const).map((c) => (
                  <button
                    key={c}
                    className={category === c ? "active" : ""}
                    onClick={() => {
                      setCategory(c);
                      setAccountFilter("");
                      setCommunityIds([]);
                      setCommunityChosen(false); // re-offer the community choice
                    }}
                  >
                    {CATEGORY_LABELS[c]}
                  </button>
                ))}
              </div>
            )}
            <button
              className="link-btn"
              onClick={() => {
                setCategory("");
                setNationalStep(false);
                setCommunityChosen(false);
                setAccountFilter("");
                setCommunityIds([]);
              }}
            >
              switch account type
            </button>
          </>
        )}
        <input
          placeholder="Search job code, address, or lot…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          value={accountFilter}
          onChange={(e) => {
            setAccountFilter(e.target.value);
            setCommunityIds([]); // reset community picks when the division/builder changes
          }}
        >
          <option value="">{isDrh ? "All divisions" : "All accounts"}</option>
          {(archived ? accounts : categoryAccounts).map((a) => (
            <option key={a.id} value={a.id}>
              {isDrh ? divisionLabel(a.name) : a.name}
            </option>
          ))}
        </select>
        {communityOptions.length > 0 && (
          <MultiSelectDropdown
            allLabel="All communities"
            selected={communityIds}
            onChange={setCommunityIds}
            options={communityOptions.map((c) => ({ value: String(c.id), label: c.name }))}
          />
        )}
        {!archived && (
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {JOB_STATUSES.filter((s) => s !== "6.0-Clsd" && s !== "8.0-Void").map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </select>
        )}
      </div>
      </div>

      {!archived && showCreate && (
        <NewJobForm
          accounts={accounts}
          onCreated={() => {
            setShowCreate(false);
            refresh();
          }}
        />
      )}

      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job code</th>
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
                  <a href={`#/jobs/${j.id}`}>{j.job_code ?? `#${j.id}`}</a>
                </td>
                <td>
                  <a href={`#/jobs/${j.id}`}>{j.address}</a>
                </td>
                <td>{j.account_name}</td>
                <td>{j.community_name ?? "—"}</td>
                <td>{j.lot_number ?? "—"}</td>
                <td>{j.job_type}</td>
                <td>
                  <span className={`badge badge-${statusSlug(j.status)}`}>{statusLabel(j.status)}</span>
                </td>
                <td>{fmtDate(j.install_date)}</td>
              </tr>
            ))}
            {jobs.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
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
    job_code: "",
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
      // all communities here — a new job may be the first in a new community
      listCommunities(Number(form.account_id), false).then(setCommunities).catch(() => {});
    } else {
      setCommunities([]);
    }
  }, [form.account_id]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createJob({
        job_code: form.job_code || null,
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
        Job code
        <input value={form.job_code} onChange={set("job_code")} placeholder="e.g. DRLICR-0113" />
      </label>
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
