import { useEffect, useState } from "react";
import { OrderingChecklist, getOrderingChecklist } from "../api";
import { fmtDate } from "../format";

export const STAGES = [
  { key: "stage1", label: "1. PO's & Selection File" },
  { key: "stage2", label: "2. Orders & Layouts" },
  { key: "stage3", label: "3. SO's & Order Comparison" },
  { key: "stage4", label: "4. POs Attached" },
] as const;

/** CabinetTron's record of the ordering pipeline. All ordering is done in
 *  Optimus (COAST suite, 11/5/26); this card only shows what Optimus pushed back. */
export default function OrderingCard({ jobId }: { jobId: number }) {
  const [checklist, setChecklist] = useState<OrderingChecklist | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getOrderingChecklist(jobId)
      .then(setChecklist)
      .catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!checklist) return null;

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
                <span className={`stage-toggle ${done ? "done" : ""}`} aria-label={done ? "done" : "not done"}>
                  {done ? "✓" : ""}
                </span>
                <span>{s.label}</span>
                {when && <span className="muted"> — {fmtDate(when)}</span>}
              </li>
            );
          })}
        </ul>
        {checklist.notes && <p className="muted">{checklist.notes}</p>}
        <p style={{ marginBottom: 0 }}>
          <a href={`/optimus#job=${jobId}`}>Open in Optimus</a> to work the order.
        </p>
      </div>
    </>
  );
}
