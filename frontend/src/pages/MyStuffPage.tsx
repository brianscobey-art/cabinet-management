import { FormEvent, useEffect, useState } from "react";
import {
  JobListItem,
  NoteRow,
  NOTE_TYPES,
  User,
  completeNote,
  createNote,
  deleteNote,
  listJobs,
  listNotes,
  listUsers,
  markNotesRead,
} from "../api";
import { fmtDate } from "../format";

/** The five COAST apps, as a compact strip at the top of the landing page. */
const APPS = [
  { name: "CabinetTron", href: "#/jobs", blurb: "Jobs & POs" },
  { name: "Optimus", href: "/ordering-platform", blurb: "Ordering" },
  { name: "Sterling", href: "/sterling", blurb: "Pricing" },
  { name: "Autobot", href: "/autobot", blurb: "Service routing" },
];

const typeLabel = (v: string) => NOTE_TYPES.find((t) => t.value === v)?.label ?? v;

function TypeBadge({ type }: { type: string }) {
  return <span className={`note-type note-type-${type}`}>{typeLabel(type)}</span>;
}

function when(iso: string) {
  const d = new Date(iso);
  return (
    d.toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "2-digit" }) +
    " " +
    d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
  );
}

/** One note/task with its replies. */
function NoteCard({
  note,
  me,
  onChange,
}: {
  note: NoteRow;
  me: User;
  onChange: () => void;
}) {
  const [reply, setReply] = useState("");
  const [open, setOpen] = useState(false);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!reply.trim()) return;
    await createNote({ body: reply, note_type: "fyi", parent_id: note.id, job_id: note.job_id });
    setReply("");
    onChange();
  }

  const done = !!note.completed_at;
  return (
    <div className={`note-card${note.unread ? " note-unread" : ""}${done ? " note-done" : ""}`}>
      <div className="note-head">
        <TypeBadge type={note.note_type} />
        {note.is_task && (
          <span className="note-task">
            {done ? "✓ Done" : "Task"} · {note.assignee_name ?? note.assignee_email}
          </span>
        )}
        {note.due_date && !done && (
          <span className={note.is_overdue ? "note-overdue" : "note-due"}>
            due {fmtDate(note.due_date)}
            {note.is_overdue ? " — overdue" : ""}
          </span>
        )}
        {note.job_code && (
          <a className="note-job" href={`#/jobs/${note.job_id}`}>
            {note.job_code}
          </a>
        )}
        <span className="note-when">{when(note.created_at)}</span>
      </div>

      <div className="note-body">{note.body}</div>

      <div className="note-foot">
        <span className="muted">{note.author_name ?? note.author_email}</span>
        {note.tags.length > 0 && <span className="muted"> · tagged {note.tags.length}</span>}
        {note.is_task && (
          <button className="link-btn" onClick={() => completeNote(note.id, !done).then(onChange)}>
            {done ? "reopen" : "mark complete"}
          </button>
        )}
        <button className="link-btn" onClick={() => setOpen((v) => !v)}>
          {note.replies.length ? `${note.replies.length} repl${note.replies.length === 1 ? "y" : "ies"}` : "reply"}
        </button>
        {(note.author_email === me.email || me.role === "admin") && (
          <button
            className="link-btn"
            onClick={() => {
              if (confirm("Delete this note and its replies?")) deleteNote(note.id).then(onChange);
            }}
          >
            delete
          </button>
        )}
      </div>

      {(open || note.replies.length > 0) && (
        <div className="note-replies">
          {note.replies.map((r) => (
            <div key={r.id} className={`note-reply${r.unread ? " note-unread" : ""}`}>
              <div className="note-body">{r.body}</div>
              <div className="muted">
                {r.author_name ?? r.author_email} · {when(r.created_at)}
              </div>
            </div>
          ))}
          {open && (
            <form className="inline-form" onSubmit={send}>
              <input
                placeholder="Write a reply…"
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                style={{ flex: 1 }}
              />
              <button type="submit">Reply</button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

export default function MyStuffPage({ me }: { me: User }) {
  const [notes, setNotes] = useState<NoteRow[]>([]);
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [showDone, setShowDone] = useState(false);
  const [users, setUsers] = useState<{ email: string; full_name: string }[]>([]);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // compose
  const [body, setBody] = useState("");
  const [noteType, setNoteType] = useState("fyi");
  const [jobId, setJobId] = useState("");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [tags, setTags] = useState<string[]>([]);

  const load = () =>
    listNotes({ scope, show_done: showDone })
      .then((rows) => {
        setNotes(rows);
        const unread = rows.flatMap((r) => [r, ...r.replies]).filter((r) => r.unread).map((r) => r.id);
        if (unread.length) markNotesRead(unread).catch(() => {});
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, showDone]);

  useEffect(() => {
    listUsers()
      .then((u) => setUsers(u.filter((x) => x.is_active).map((x) => ({ email: x.email, full_name: x.full_name }))))
      .catch(() => {});
    listJobs({}).then(setJobs).catch(() => {});
  }, []);

  async function post(e: FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createNote({
        body,
        note_type: noteType,
        job_id: jobId ? Number(jobId) : null,
        assignee_email: assignee || null,
        due_date: due || null,
        tags,
      });
      setBody("");
      setJobId("");
      setAssignee("");
      setDue("");
      setTags([]);
      setNoteType("fyi");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {/* COAST launcher strip */}
      <div className="coast-strip">
        {APPS.map((a) => (
          <a key={a.name} className="coast-chip" href={a.href}>
            <b>{a.name}</b>
            <span>{a.blurb}</span>
          </a>
        ))}
        <a className="coast-chip coast-more" href="#/suite">
          All apps →
        </a>
      </div>

      <div className="page-head">
        <h2>My Stuff</h2>
        <div className="view-toggle">
          <button className={scope === "mine" ? "active" : ""} onClick={() => setScope("mine")}>
            Mine
          </button>
          <button className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>
            Everything
          </button>
        </div>
      </div>

      {/* Compose */}
      <form className="note-compose" onSubmit={post}>
        <textarea
          rows={2}
          placeholder="Write a note, ask a question, or assign a task…"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <div className="note-compose-row">
          <select value={noteType} onChange={(e) => setNoteType(e.target.value)}>
            {NOTE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
            <option value="">— no job —</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.job_code ?? `#${j.id}`} · {j.address}
              </option>
            ))}
          </select>
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">— no assignee —</option>
            {users.map((u) => (
              <option key={u.email} value={u.email}>
                Assign: {u.full_name}
              </option>
            ))}
          </select>
          {assignee && (
            <input
              type="date"
              className="date-input"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              title="Due date (optional)"
            />
          )}
          <select
            value=""
            onChange={(e) => {
              if (e.target.value && !tags.includes(e.target.value)) setTags([...tags, e.target.value]);
            }}
          >
            <option value="">+ tag someone</option>
            {users
              .filter((u) => !tags.includes(u.email))
              .map((u) => (
                <option key={u.email} value={u.email}>
                  {u.full_name}
                </option>
              ))}
          </select>
          <button type="submit" disabled={busy}>
            {busy ? "Posting…" : "Post"}
          </button>
        </div>
        {tags.length > 0 && (
          <div className="note-tags">
            {tags.map((t) => (
              <button key={t} type="button" className="tag-chip" onClick={() => setTags(tags.filter((x) => x !== t))}>
                {users.find((u) => u.email === t)?.full_name ?? t} ✕
              </button>
            ))}
          </div>
        )}
      </form>

      {error && <p className="error">{error}</p>}

      <div className="note-filters">
        <label className="muted">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> show
          completed tasks
        </label>
      </div>

      {notes.length === 0 ? (
        <p className="muted">
          {scope === "mine"
            ? "Nothing for you right now. Switch to Everything to see the team's notes."
            : "No notes yet — post the first one above."}
        </p>
      ) : (
        notes.map((n) => <NoteCard key={n.id} note={n} me={me} onChange={load} />)
      )}

      {/* Summary reports land here later */}
      <div className="card" style={{ marginTop: "1.25rem" }}>
        <h3 style={{ marginTop: 0 }}>Summary reports</h3>
        <p className="muted">Coming soon — your key numbers will show up here.</p>
      </div>
    </div>
  );
}
