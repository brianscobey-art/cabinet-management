import { useEffect, useMemo, useState } from "react";
import { FMNoteReportRow, getFieldMeasureNotes, markFieldMeasureNotesSent } from "../api";
import { fmtLot4 } from "../format";
import { initials } from "./PhasesPage";

// Field measure notes -> Alex (Brian 11/11/26): check the notes, compile them
// into an Outlook email, then mark them sent so none go twice.
const TO_KEY = "fmNotesTo";
const DEFAULT_TO = "alex.talley@carterlumber.com";
// Outlook on the web drops a compose link much past this; longer bodies go by paste.
const MAX_LINK = 7500;

// created_at is UTC; show the local day as m/d/yy
const day = (iso: string) => {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}/${String(d.getFullYear()).slice(2)}`;
};

interface House {
  job_id: number;
  head: FMNoteReportRow;
  notes: FMNoteReportRow[];
}

const lotLabel = (r: FMNoteReportRow) => (r.lot_number ? `Lot ${fmtLot4(r.lot_number)}` : r.job_code ?? `#${r.job_id}`);

function compile(houses: House[], picked: Set<number>) {
  const parts: string[] = [];
  let n = 0;
  for (const h of houses) {
    const notes = h.notes.filter((x) => picked.has(x.id));
    if (!notes.length) continue;
    const r = h.head;
    parts.push(
      [
        `${r.job_code ?? ""} — ${lotLabel(r)}, ${r.community_name ?? "no community"} (${r.account_name ?? ""})`,
        `${r.address}${r.plan ? ` · ${r.plan}` : ""}`,
        ...notes.map((x) => `  • ${day(x.created_at)} (${initials(x.author)}): ${x.body}`),
      ].join("\n"),
    );
    n += 1;
  }
  const today = day(new Date().toISOString());
  return {
    subject: `Field measure notes — ${today} (${n} house${n === 1 ? "" : "s"})`,
    body: `Alex,\n\nField measure notes from CabinetTron:\n\n${parts.join("\n\n")}\n\nThanks`,
  };
}

export default function FieldMeasureNotesView() {
  const [rows, setRows] = useState<FMNoteReportRow[] | null>(null);
  const [error, setError] = useState("");
  const [showSent, setShowSent] = useState(false);
  const [builder, setBuilder] = useState("");
  const [community, setCommunity] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [to, setTo] = useState(() => {
    try {
      return localStorage.getItem(TO_KEY) || DEFAULT_TO;
    } catch {
      return DEFAULT_TO;
    }
  });
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    getFieldMeasureNotes(showSent)
      .then((r) => {
        setRows(r);
        setPicked((p) => new Set([...p].filter((id) => r.some((x) => x.id === id))));
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showSent]);

  const builders = useMemo(() => [...new Set((rows ?? []).map((r) => r.account_name ?? ""))].sort(), [rows]);
  const communities = useMemo(
    () =>
      [...new Set((rows ?? []).filter((r) => !builder || r.account_name === builder).map((r) => r.community_name ?? ""))].sort(),
    [rows, builder],
  );

  const houses = useMemo(() => {
    const m = new Map<number, House>();
    for (const r of rows ?? []) {
      if (builder && r.account_name !== builder) continue;
      if (community && r.community_name !== community) continue;
      const h = m.get(r.job_id) ?? { job_id: r.job_id, head: r, notes: [] };
      h.notes.push(r);
      m.set(r.job_id, h);
    }
    const list = [...m.values()];
    for (const h of list) h.notes.sort((a, b) => a.created_at.localeCompare(b.created_at));
    return list.sort(
      (a, b) =>
        (a.head.account_name ?? "").localeCompare(b.head.account_name ?? "") ||
        (a.head.community_name ?? "").localeCompare(b.head.community_name ?? "") ||
        (a.head.job_code ?? "").localeCompare(b.head.job_code ?? ""),
    );
  }, [rows, builder, community]);

  const visibleIds = houses.flatMap((h) => h.notes.map((n) => n.id));
  const pickedVisible = visibleIds.filter((id) => picked.has(id));
  const toggle = (ids: number[], on: boolean) =>
    setPicked((p) => {
      const next = new Set(p);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });

  function saveTo(v: string) {
    setTo(v);
    try {
      localStorage.setItem(TO_KEY, v);
    } catch {
      /* per-viewer convenience only */
    }
  }

  async function openOutlook() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(draft.body);
    } catch {
      /* clipboard can be blocked; the link still carries the body when it fits */
    }
    const base = `https://outlook.office.com/mail/deeplink/compose?to=${encodeURIComponent(to)}&subject=${encodeURIComponent(draft.subject)}`;
    const full = `${base}&body=${encodeURIComponent(draft.body)}`;
    if (full.length <= MAX_LINK) {
      window.open(full, "_blank");
      setMsg("Outlook opened with the email filled in (also copied). Send it there, then click Mark sent.");
    } else {
      window.open(base, "_blank");
      setMsg("Too long for a link — the notes are copied. Paste them into the Outlook email (Ctrl+V), send, then click Mark sent.");
    }
  }

  async function copyDraft() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`);
      setMsg("Copied.");
    } catch {
      setMsg("Couldn't reach the clipboard — select the text and copy it.");
    }
  }

  async function markSent(ids: number[], sent: boolean) {
    setBusy(true);
    try {
      await markFieldMeasureNotesSent(ids, sent ? to : null, sent);
      if (sent) {
        setPicked(new Set());
        setDraft(null);
        setMsg(`Marked ${ids.length} note${ids.length === 1 ? "" : "s"} sent.`);
      }
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;

  return (
    <div className="fmn-view">
      <div className="filters">
        <select value={builder} onChange={(e) => { setBuilder(e.target.value); setCommunity(""); }}>
          <option value="">All builders</option>
          {builders.map((b) => (
            <option key={b} value={b}>{b || "—"}</option>
          ))}
        </select>
        <select value={community} onChange={(e) => setCommunity(e.target.value)}>
          <option value="">All communities</option>
          {communities.map((c) => (
            <option key={c} value={c}>{c || "—"}</option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={showSent} onChange={(e) => setShowSent(e.target.checked)} /> show sent
        </label>
      </div>

      <div className="filters">
        <label className="check">
          <input
            type="checkbox"
            checked={visibleIds.length > 0 && pickedVisible.length === visibleIds.length}
            onChange={(e) => toggle(visibleIds, e.target.checked)}
          />{" "}
          Select all
        </label>
        <span className="muted">
          {pickedVisible.length} of {visibleIds.length} note{visibleIds.length === 1 ? "" : "s"} checked ·{" "}
          {houses.length} house{houses.length === 1 ? "" : "s"}
        </span>
        <label className="check">
          To <input type="email" value={to} onChange={(e) => saveTo(e.target.value)} style={{ width: "16rem" }} />
        </label>
        <button disabled={!pickedVisible.length} onClick={() => { setMsg(""); setDraft(compile(houses, picked)); }}>
          Compile email
        </button>
      </div>

      {draft && (
        <div className="card" style={{ margin: "0.6rem 0" }}>
          <label style={{ display: "block", marginBottom: "0.4rem" }}>
            Subject{" "}
            <input value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} style={{ width: "100%" }} />
          </label>
          <textarea
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })}
            rows={Math.min(24, draft.body.split("\n").length + 1)}
            style={{ width: "100%", fontFamily: "inherit" }}
          />
          <div className="filters" style={{ marginTop: "0.4rem" }}>
            <button onClick={openOutlook}>Open in Outlook</button>
            <button onClick={copyDraft}>Copy</button>
            <button disabled={busy} onClick={() => markSent(pickedVisible, true)}>
              Mark {pickedVisible.length} sent
            </button>
            <button className="link-btn" onClick={() => setDraft(null)}>close</button>
          </div>
          {msg && <p className="muted">{msg}</p>}
        </div>
      )}
      {!draft && msg && <p className="muted">{msg}</p>}

      {houses.length === 0 ? (
        <p className="muted">{showSent ? "No field measure notes." : "No unsent field measure notes."}</p>
      ) : (
        <div className="fm-note-groups">
          {houses.map((h) => {
            const ids = h.notes.map((n) => n.id);
            const all = ids.every((id) => picked.has(id));
            return (
              <div className="fm-note-group" key={h.job_id}>
                <div className="fm-note-lot">
                  <input type="checkbox" checked={all} onChange={(e) => toggle(ids, e.target.checked)} />{" "}
                  <a href={`#/jobs/${h.job_id}`}>{h.head.job_code ?? `#${h.job_id}`}</a>{" "}
                  <span className="muted">
                    · {lotLabel(h.head)} · {h.head.community_name ?? "—"} · {h.head.account_name ?? "—"} · {h.head.address}
                    {h.head.plan ? ` · ${h.head.plan}` : ""}
                  </span>
                </div>
                {h.notes.map((n) => (
                  <label className="fm-note-line pick" key={n.id} style={{ cursor: "pointer" }}>
                    <input type="checkbox" checked={picked.has(n.id)} onChange={(e) => toggle([n.id], e.target.checked)} />
                    <span className="fm-note-meta">
                      {day(n.created_at)} · {initials(n.author)}
                    </span>
                    <span className="fm-note-body">
                      {n.body}
                      {n.sent_at && (
                        <span className="muted">
                          {" "}— sent {day(n.sent_at)}
                          {n.sent_to ? ` to ${n.sent_to}` : ""}
                          {n.sent_by ? ` by ${initials(n.sent_by)}` : ""}{" "}
                          <button
                            className="link-btn"
                            disabled={busy}
                            onClick={(e) => { e.preventDefault(); markSent([n.id], false); }}
                          >
                            unmark
                          </button>
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
