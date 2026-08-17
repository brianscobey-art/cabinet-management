import { useEffect, useRef, useState } from "react";
import { JobListItem, listJobs } from "../api";

/** Global job search that lives in the app header (shows on every page). */
export default function HeaderJobSearch() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<JobListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    const t = setTimeout(() => {
      listJobs({ q: term })
        .then((rows) => {
          setResults(rows.slice(0, 8));
          setActive(0);
          setOpen(true);
        })
        .catch(() => {});
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const go = (id: number) => {
    setQ("");
    setResults([]);
    setOpen(false);
    window.location.hash = `#/jobs/${id}`;
  };

  const term = q.trim();
  return (
    <div className="hdr-search" ref={boxRef}>
      <input
        className="hdr-search-input"
        placeholder="🔍 Search jobs — code or address"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            setActive((a) => Math.min(a + 1, results.length - 1));
            e.preventDefault();
          } else if (e.key === "ArrowUp") {
            setActive((a) => Math.max(a - 1, 0));
            e.preventDefault();
          } else if (e.key === "Enter" && results[active]) {
            go(results[active].id);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && results.length > 0 && (
        <ul className="hdr-search-results">
          {results.map((r, i) => (
            <li
              key={r.id}
              className={i === active ? "active" : ""}
              onMouseDown={() => go(r.id)}
              onMouseEnter={() => setActive(i)}
            >
              <b>{r.job_code ?? `#${r.id}`}</b>
              <span className="hdr-search-addr">{r.address}</span>
              {r.community_name && <span className="hdr-search-comm">{r.community_name}</span>}
            </li>
          ))}
        </ul>
      )}
      {open && term.length >= 2 && results.length === 0 && (
        <ul className="hdr-search-results">
          <li className="hdr-search-empty">No jobs match “{term}”</li>
        </ul>
      )}
    </div>
  );
}
