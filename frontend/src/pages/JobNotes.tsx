import { FormEvent, useEffect, useState } from "react";
import { JobNote, addJobNote, listJobNotes } from "../api";
import { fmtDate } from "../format";

// "Brian Scobey" -> "Brian S."
function shortName(full: string | null): string {
  if (!full) return "—";
  const parts = full.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : parts[0];
}

export default function JobNotes({ jobId }: { jobId: number }) {
  const [notes, setNotes] = useState<JobNote[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listJobNotes(jobId).then(setNotes).catch((e) => setError(e.message));
  }, [jobId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    setError("");
    try {
      const note = await addJobNote(jobId, body.trim());
      setNotes((ns) => [note, ...ns]);
      setBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save note");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3>Job notes</h3>
      <div className="card">
        <form className="inline-form" style={{ marginBottom: notes.length ? "1rem" : 0 }} onSubmit={submit}>
          <input
            placeholder="Add a note…"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            style={{ flex: 1, minWidth: "16rem" }}
          />
          <button type="submit" disabled={busy || !body.trim()}>
            Save notes
          </button>
          {error && <span className="error">{error}</span>}
        </form>
        {notes.map((n) => (
          <div key={n.id} className="note-entry">
            <div className="note-body">{n.body}</div>
            <div className="note-meta muted">
              {fmtDate(n.created_at)} · {shortName(n.author)}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
