import { useState } from "react";
import { CHANGELOG } from "../changelog";
import { HELP_SECTIONS, HelpTopic } from "../helpContent";
import { User } from "../api";

/**
 * Help / User Guide. Works two ways:
 *  - signed in (me set) — shown inside the app shell via the Help tab; admins
 *    also see admin-only topics.
 *  - public (me undefined) — reached from the login page; admin topics hidden,
 *    and a "back to sign in" bar is shown.
 */
export default function HelpPage({ me }: { me?: User }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isAdmin = me?.role === "admin";
  const isPublic = !me;

  const q = query.trim().toLowerCase();
  const matches = (t: HelpTopic) =>
    !q ||
    t.q.toLowerCase().includes(q) ||
    (t.a?.toLowerCase().includes(q) ?? false) ||
    (t.steps?.some((s) => s.toLowerCase().includes(q)) ?? false);

  const sections = HELP_SECTIONS.map((sec) => ({
    ...sec,
    topics: sec.topics.filter((t) => (!t.adminOnly || isAdmin) && matches(t)),
  })).filter((sec) => sec.topics.length > 0);

  const key = (si: number, ti: number) => `${si}:${ti}`;
  const isOpen = (si: number, ti: number) => (q ? true : !!open[key(si, ti)]);

  return (
    <div>
      {isPublic && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 16px",
            background: "#125952",
            color: "#fff",
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          <img src="/carter-logo.png" alt="Carter Lumber" style={{ height: 26 }} />
          <b style={{ fontSize: "1.05rem" }}>Help &amp; User Guide</b>
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              window.location.hash = "#";
            }}
            style={{ marginLeft: "auto", color: "#fff", fontWeight: 600 }}
          >
            ← Back to sign in
          </a>
        </div>
      )}

      {!isPublic && (
        <div className="page-head">
          <h2>Help &amp; Training</h2>
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>What's new</h3>
        <ul className="changelog" style={{ listStyle: "none", paddingLeft: 0 }}>
          {CHANGELOG.map((c, i) => (
            <li key={i} style={{ marginBottom: 10 }}>
              <span className="muted" style={{ display: "inline-block", minWidth: 64 }}>
                {c.date}
              </span>
              <b>{c.title}</b>
              <div className="muted" style={{ marginLeft: 64 }}>
                {c.detail}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div style={{ margin: "16px 0" }}>
        <input
          type="search"
          placeholder="Search the guide…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: "100%", maxWidth: 420, padding: "8px 12px", fontSize: "1rem" }}
        />
      </div>

      {sections.length === 0 && <p className="muted">No help topics match “{query}”.</p>}

      {sections.map((sec, si) => (
        <div key={sec.title} className="card" style={{ marginBottom: 14 }}>
          <h3 style={{ marginTop: 0 }}>{sec.title}</h3>
          {sec.blurb && <p className="muted">{sec.blurb}</p>}
          {sec.topics.map((t, ti) => (
            <div
              key={t.q}
              style={{ borderTop: ti ? "1px solid #eee" : undefined, padding: "8px 0" }}
            >
              <button
                className="link-btn"
                style={{ fontWeight: 600, fontSize: "1rem", textAlign: "left" }}
                onClick={() => setOpen((o) => ({ ...o, [key(si, ti)]: !o[key(si, ti)] }))}
              >
                {isOpen(si, ti) ? "▾ " : "▸ "}
                {t.q}
              </button>
              {isOpen(si, ti) && (
                <div style={{ margin: "6px 0 2px 18px" }}>
                  {t.a && <p style={{ marginTop: 0 }}>{t.a}</p>}
                  {t.steps && (
                    <ol style={{ marginTop: t.a ? 4 : 0 }}>
                      {t.steps.map((s, i) => (
                        <li key={i} style={{ marginBottom: 3 }}>
                          {s}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}

      <p className="muted" style={{ marginTop: 8 }}>
        Missing something, or want a step explained better? Tell Brian and it'll get added here.
      </p>
    </div>
  );
}
