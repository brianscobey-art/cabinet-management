import { useEffect, useState } from "react";
import { ServiceRequestSummary, createServiceRequest, listServiceRequests } from "../api";
import { fmtDate } from "../format";

export default function ServiceRequestsSection({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [rows, setRows] = useState<ServiceRequestSummary[]>([]);
  const [error, setError] = useState("");

  const load = () => listServiceRequests(jobId).then(setRows).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function create() {
    try {
      const sr = await createServiceRequest(jobId, null);
      window.location.hash = `#/service/${sr.id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <>
      <div className="page-head kb-head-row">
        <h3 className="kb-head" style={{ margin: 0 }}>
          Service Requests
        </h3>
        {canWrite && <button onClick={create}>+ New service request</button>}
      </div>
      {error && <p className="error">{error}</p>}
      {rows.length === 0 ? (
        <p className="muted">No service requests yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th className="num">Parts</th>
                <th className="num">Lines</th>
                <th>Created</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <a href={`#/service/${r.id}`}>{r.title || `Service request #${r.id}`}</a>
                  </td>
                  <td>
                    <span className="badge">{r.status}</span>
                  </td>
                  <td className="num">{r.part_count}</td>
                  <td className="num">{r.line_count}</td>
                  <td>
                    {fmtDate(r.created_at)}
                    {r.created_by ? ` · ${r.created_by}` : ""}
                  </td>
                  <td>
                    <a className="link-btn" href={`#/service/${r.id}`}>
                      open →
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
