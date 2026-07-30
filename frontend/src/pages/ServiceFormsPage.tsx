import { ChangeEvent, useEffect, useRef, useState } from "react";
import {
  Account,
  Community,
  JobListItem,
  createServiceRequest,
  downloadServiceTemplate,
  importServiceExcel,
  listAccounts,
  listCommunities,
  listJobs,
} from "../api";

export default function ServiceFormsPage({ canWrite }: { canWrite: boolean }) {
  const [builders, setBuilders] = useState<Account[]>([]);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [builderId, setBuilderId] = useState("");
  const [communityId, setCommunityId] = useState("");
  const [jobId, setJobId] = useState("");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<JobListItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listAccounts().then((a) => setBuilders(a.filter((x) => x.type === "builder"))).catch(() => {});
  }, []);
  useEffect(() => {
    setCommunityId("");
    setJobId("");
    setJobs([]);
    if (builderId) listCommunities(Number(builderId)).then(setCommunities).catch(() => {});
    else setCommunities([]);
  }, [builderId]);
  useEffect(() => {
    setJobId("");
    if (communityId) listJobs({ community_id: communityId }).then(setJobs).catch(() => {});
    else setJobs([]);
  }, [communityId]);

  const selectedJob =
    jobs.find((j) => String(j.id) === jobId) || results?.find((j) => String(j.id) === jobId) || null;

  async function search() {
    if (!q.trim()) return;
    setError("");
    try {
      setResults(await listJobs({ q: q.trim() }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    }
  }

  async function createFor(id: number) {
    setBusy(true);
    setError("");
    try {
      const sr = await createServiceRequest(id, null);
      window.location.hash = `#/service/${sr.id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function onImport(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const sr = await importServiceExcel(file);
      window.location.hash = `#/service/${sr.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const jobLabel = (j: JobListItem) =>
    `${j.lot_number ? `Lot ${j.lot_number} — ` : ""}${j.address}${j.job_code ? ` (${j.job_code})` : ""}`;

  return (
    <div>
      <p className="back-row">
        <a href="#/forms">← Forms</a>
      </p>
      <div className="page-head">
        <h2>Service Request Form</h2>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>Load a job</h3>
        <p className="muted">Pick the builder, community and lot — or search by job code. The service report saves to that job.</p>
        <div className="filters">
          <select value={builderId} onChange={(e) => setBuilderId(e.target.value)}>
            <option value="">Builder…</option>
            {builders.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          {builderId && (
            <select value={communityId} onChange={(e) => setCommunityId(e.target.value)}>
              <option value="">Community…</option>
              {communities.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          {communityId && (
            <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
              <option value="">Lot / job…</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {jobLabel(j)}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="filters" style={{ marginTop: "0.5rem" }}>
          <input
            placeholder="…or search job code / address"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            style={{ minWidth: "16rem" }}
          />
          <button onClick={search}>Search</button>
        </div>
        {results && (
          <div className="filters" style={{ marginTop: "0.4rem" }}>
            {results.length === 0 ? (
              <span className="muted">No matches.</span>
            ) : (
              <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
                <option value="">{results.length} match{results.length === 1 ? "" : "es"}…</option>
                {results.map((j) => (
                  <option key={j.id} value={j.id}>
                    {jobLabel(j)}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {selectedJob && (
          <p style={{ marginTop: "0.75rem" }}>
            <strong>{jobLabel(selectedJob)}</strong>
            <br />
            <button disabled={!canWrite || busy} onClick={() => createFor(selectedJob.id)}>
              Create service request on this job →
            </button>
          </p>
        )}
      </div>

      <div className="card">
        <h3>Blank form</h3>
        <div className="filters">
          <a className="report-open" href="#/service-blank">
            🖨 Print a blank form
          </a>
          <button onClick={() => downloadServiceTemplate().catch((e) => setError(e.message))}>
            ⬇ Download Excel template
          </button>
          {canWrite && (
            <>
              <button disabled={busy} onClick={() => fileRef.current?.click()}>
                ⬆ Import filled Excel
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx"
                style={{ display: "none" }}
                onChange={onImport}
              />
            </>
          )}
        </div>
        <p className="muted" style={{ marginTop: "0.4rem" }}>
          The Excel template has a Job Code cell — fill it in and the import attaches the report to that job.
        </p>
      </div>
    </div>
  );
}
