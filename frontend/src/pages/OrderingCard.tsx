import { useEffect, useState } from "react";
import { OrderingChecklist, getOrderingChecklist, updateOrderingChecklist } from "../api";
import { fmtDate } from "../format";
import { STAGES } from "./OrderingPage";

export default function OrderingCard({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [checklist, setChecklist] = useState<OrderingChecklist | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getOrderingChecklist(jobId)
      .then((c) => {
        setChecklist(c);
        setNotes(c.notes ?? "");
      })
      .catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!checklist) return null;

  async function toggle(stageKey: (typeof STAGES)[number]["key"]) {
    if (!checklist) return;
    const doneKey = `${stageKey}_done` as const;
    const updated = await updateOrderingChecklist(jobId, { [doneKey]: !checklist[doneKey] });
    setChecklist(updated);
  }

  return (
    <>
      <h3>Ordering pipeline</h3>
      <div className="card">
        <ul className="stage-list">
          {STAGES.map((s) => {
            const done = checklist[`${s.key}_done`];
            const when = checklist[`${s.key}_date`];
            return (
              <li key={s.key}>
                <button
                  className={`stage-toggle ${done ? "done" : ""}`}
                  disabled={!canWrite}
                  onClick={() => toggle(s.key).catch((e) => setError(e.message))}
                >
                  {done ? "✓" : ""}
                </button>
                <span>{s.label}</span>
                {when && <span className="muted"> — {fmtDate(when)}</span>}
              </li>
            );
          })}
        </ul>
        {canWrite && (
          <div className="inline-form" style={{ marginBottom: 0 }}>
            <input
              placeholder="Ordering notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              style={{ flex: 1, minWidth: "14rem" }}
            />
            <button
              onClick={async () => {
                const updated = await updateOrderingChecklist(jobId, { notes });
                setChecklist(updated);
              }}
            >
              Save notes
            </button>
          </div>
        )}
        {!canWrite && checklist.notes && <p className="muted">{checklist.notes}</p>}
      </div>
    </>
  );
}
