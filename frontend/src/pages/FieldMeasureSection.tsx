import { useEffect, useState } from "react";
import { FieldMeasureDetail, getFieldMeasure } from "../api";
import { fmtDate } from "../format";
import { initials } from "./PhasesPage";

function Stamp({ on, by, at }: { on: boolean; by: string | null; at: string | null }) {
  if (!on) return <span className="muted">—</span>;
  return (
    <span className="fm-stamp">
      ✓{by || at ? ` · ${initials(by)}${at ? ` · ${fmtDate(at)}` : ""}` : ""}
    </span>
  );
}

export default function FieldMeasureSection({
  jobId,
  redMeasureDate,
}: {
  jobId: number;
  redMeasureDate: string | null;
}) {
  const [fm, setFm] = useState<FieldMeasureDetail | null>(null);

  useEffect(() => {
    getFieldMeasure(jobId).then(setFm).catch(() => {});
  }, [jobId]);

  return (
    <div className="card fm-card">
      <h3>Field Measure</h3>
      <dl>
        <dt>Red field measure</dt>
        <dd>{redMeasureDate ? fmtDate(redMeasureDate) : "—"}</dd>
        <dt>Field measure complete</dt>
        <dd>{fm?.complete_date ? fmtDate(fm.complete_date) : "—"}</dd>
        <dt>Correct</dt>
        <dd>
          <Stamp on={!!fm?.correct} by={fm?.correct_by ?? null} at={fm?.correct_at ?? null} />
        </dd>
        <dt>Incorrect</dt>
        <dd>
          <Stamp on={!!fm?.incorrect} by={fm?.incorrect_by ?? null} at={fm?.incorrect_at ?? null} />
        </dd>
        <dt>Super notified</dt>
        <dd>
          <Stamp
            on={!!fm?.super_notified}
            by={fm?.super_notified_by ?? null}
            at={fm?.super_notified_at ?? null}
          />
        </dd>
      </dl>
      <div className="fm-card-notes">
        <strong>Field Measure Notes</strong>
        {fm && fm.notes.length > 0 ? (
          <ul className="fm-notes-list">
            {fm.notes.map((n) => (
              <li key={n.id}>
                <span className="fm-note-meta">
                  {fmtDate(n.created_at)} · {initials(n.author)}
                </span>
                <span className="fm-note-body">{n.body}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted" style={{ margin: "0.35rem 0 0" }}>
            No field measure notes.
          </p>
        )}
      </div>
    </div>
  );
}
