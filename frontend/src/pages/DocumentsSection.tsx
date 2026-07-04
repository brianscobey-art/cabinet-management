import { FormEvent, useEffect, useState } from "react";
import { JobDocument, listDocuments, openDocument, registerDocument, removeDocument } from "../api";

const TYPE_LABELS: Record<string, string> = {
  layout: "Layout",
  order: "Order",
  po: "PO",
  sales_order: "Sales Order",
  selections: "Selections",
  summary: "Summary",
  document: "Document",
};

export default function DocumentsSection({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [docs, setDocs] = useState<JobDocument[]>([]);
  const [error, setError] = useState("");
  const [path, setPath] = useState("");

  const refresh = () => listDocuments(jobId).then(setDocs).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function attach(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await registerDocument(jobId, { file_path: path });
      setPath("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <>
      <h3>Documents</h3>
      {error && <p className="error">{error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>File</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td>
                  <span className="badge">{TYPE_LABELS[d.doc_type] ?? d.doc_type}</span>
                </td>
                <td>
                  <button
                    className="link-btn"
                    onClick={() => openDocument(d.id).catch((e) => setError(e.message))}
                  >
                    {d.filename}
                  </button>
                </td>
                <td>
                  {canWrite && (
                    <button
                      className="link-btn"
                      onClick={async () => {
                        await removeDocument(d.id).catch((e) => setError(e.message));
                        refresh();
                      }}
                    >
                      remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr>
                <td colSpan={3} className="muted">
                  No documents attached.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canWrite && (
        <form className="inline-form" onSubmit={attach}>
          <input
            placeholder="Full path to file (OneDrive, network share…)"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            required
            style={{ width: "26rem", maxWidth: "100%" }}
          />
          <button type="submit">Attach</button>
        </form>
      )}
    </>
  );
}
