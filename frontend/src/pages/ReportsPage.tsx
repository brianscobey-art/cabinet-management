import { useEffect, useMemo, useRef, useState } from "react";
import { PhaseReportRow, getPhaseReport, openDocument } from "../api";
import { fmtDate } from "../format";

const REPORT_LIST = [
  {
    key: "phases",
    name: "Phase Report",
    desc: "All active houses by builder, community, and lot with current construction phase.",
    available: true,
  },
  {
    key: "ordering",
    name: "Ordering Status Report",
    desc: "The 4-stage ordering pipeline across builder jobs — what's waiting on POs, layouts, or SO comparison.",
    available: false,
  },
  {
    key: "open-po",
    name: "Open PO Report",
    desc: "Open builder POs with amounts and totals by division and community.",
    available: false,
  },
  {
    key: "install-week",
    name: "Install Week Report",
    desc: "Scheduled installs grouped by week, community, and installer.",
    available: false,
  },
  {
    key: "delivery",
    name: "Delivery Report",
    desc: "Upcoming cabinet deliveries and confirmation status — the day-before check.",
    available: false,
  },
  {
    key: "warranty",
    name: "Warranty & Service Report",
    desc: "Open claims, installer callback rates, and service cost.",
    available: false,
  },
];

export default function ReportsPage({ hash }: { hash: string }) {
  if (hash.startsWith("#/reports/phases")) return <PhaseReport />;
  return <ReportsIndex />;
}

function ReportsIndex() {
  return (
    <div>
      <div className="page-head">
        <h2>Reports</h2>
      </div>
      <div className="report-list">
        {REPORT_LIST.map((r) => (
          <div key={r.key} className={`card report-card ${r.available ? "" : "planned"}`}>
            <div>
              <h3>{r.name}</h3>
              <p className="muted">{r.desc}</p>
            </div>
            {r.available ? (
              <a className="report-open" href={`#/reports/${r.key}`}>
                Open →
              </a>
            ) : (
              <span className="badge">coming soon</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

interface CommunityGroup {
  key: string;
  builder: string;
  community: string;
  rows: PhaseReportRow[];
}

function PhaseReport() {
  const [rows, setRows] = useState<PhaseReportRow[]>([]);
  const [builders, setBuilders] = useState<string[]>([]);
  const [selectedBuilders, setSelectedBuilders] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set()); // community group keys
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    getPhaseReport()
      .then((r) => {
        setRows(r);
        setBuilders([...new Set(r.map((row) => row.account_name))].sort());
      })
      .catch((e) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, CommunityGroup>();
    for (const row of rows) {
      const key = groupKey(row);
      if (!map.has(key)) {
        map.set(key, {
          key,
          builder: row.account_name,
          community: row.community_name ?? "(no community)",
          rows: [],
        });
      }
      map.get(key)!.rows.push(row);
    }
    return [...map.values()];
  }, [rows]);

  const visibleGroups = groups.filter((g) => selectedBuilders.has(g.builder));

  function toggleBuilder(name: string) {
    setSelectedBuilders((s) => {
      const next = new Set(s);
      const theirGroups = groups.filter((g) => g.builder === name).map((g) => g.key);
      if (next.has(name)) {
        next.delete(name);
        setSelected((sel) => {
          const ns = new Set(sel);
          theirGroups.forEach((k) => ns.delete(k));
          return ns;
        });
      } else {
        next.add(name);
        setSelected((sel) => new Set([...sel, ...theirGroups])); // new builder's communities start selected
      }
      return next;
    });
  }

  function toggleCommunity(key: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleExpand(key: string) {
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const selectedCount = visibleGroups.filter((g) => selected.has(g.key)).length;

  return (
    <div>
      <div className="page-sticky no-print">
        <div className="page-head">
          <h2>
            <a href="#/reports" className="crumb">
              Reports
            </a>{" "}
            / Phase Report
          </h2>
          <button onClick={() => window.print()} disabled={selectedCount === 0}>
            🖨 Print {selectedCount} communit{selectedCount === 1 ? "y" : "ies"}
          </button>
        </div>
        <div className="filters">
          <MultiSelect
            label="Builders"
            options={builders}
            selected={selectedBuilders}
            onToggle={toggleBuilder}
            onAll={() => builders.forEach((b) => !selectedBuilders.has(b) && toggleBuilder(b))}
            onNone={() => builders.forEach((b) => selectedBuilders.has(b) && toggleBuilder(b))}
          />
          {visibleGroups.length > 0 && (
            <>
              <button className="link-btn" onClick={() => setSelected(new Set([...selected, ...visibleGroups.map((g) => g.key)]))}>
                select all communities
              </button>
              <button className="link-btn" onClick={() => setSelected(new Set())}>
                select none
              </button>
              <button className="link-btn" onClick={() => setExpanded(new Set(visibleGroups.map((g) => g.key)))}>
                expand all
              </button>
              <button className="link-btn" onClick={() => setExpanded(new Set())}>
                collapse all
              </button>
              <span className="muted" style={{ alignSelf: "center" }}>
                {selectedCount} of {visibleGroups.length} communities selected for print
              </span>
            </>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {selectedBuilders.size === 0 && (
        <p className="muted">Pick one or more builders to see their communities.</p>
      )}

      <div className="print-title print-only">
        Carter Kitchen and Bath — Phase Report — {fmtDate(new Date().toISOString())}
      </div>

      {visibleGroups.map((g) => (
        <section
          key={g.key}
          className={`report-group ${selected.has(g.key) ? "" : "print-skip"} ${
            expanded.has(g.key) ? "" : "collapsed"
          }`}
        >
          <div className="report-group-head">
            <label className="check-inline no-print">
              <input type="checkbox" checked={selected.has(g.key)} onChange={() => toggleCommunity(g.key)} />
            </label>
            <button
              className="expand-arrow no-print"
              onClick={() => toggleExpand(g.key)}
              title={expanded.has(g.key) ? "Collapse" : "Expand"}
            >
              {expanded.has(g.key) ? "▾" : "▸"}
            </button>
            <h3 className="clickable-head" onClick={() => toggleExpand(g.key)}>
              {g.builder} — {g.community}
              <span className="muted"> ({g.rows.length} house{g.rows.length === 1 ? "" : "s"})</span>
            </h3>
          </div>
          <div className="table-wrap report-table">
            <table>
              <thead>
                <tr>
                  <th>Lot</th>
                  <th>Job code</th>
                  <th>Address</th>
                  <th>Plan</th>
                  <th>Field Measure</th>
                  <th>Current phase</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.job_id}>
                    <td>{r.lot_number ?? "—"}</td>
                    <td>
                      <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                    </td>
                    <td>{r.address}</td>
                    <td>{r.plan ?? "—"}</td>
                    <td>
                      {r.measure_date ? fmtDate(r.measure_date) : "—"}
                      {r.layout_doc_id && (
                        <>
                          {" "}
                          <button
                            className="link-btn no-print"
                            onClick={() => openDocument(r.layout_doc_id!)}
                          >
                            layout
                          </button>
                        </>
                      )}
                    </td>
                    <td>{r.phase_label ?? "—"}</td>
                    <td>{r.phase_date ? fmtDate(r.phase_date) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function MultiSelect({
  label,
  options,
  selected,
  onToggle,
  onAll,
  onNone,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onToggle: (name: string) => void;
  onAll: () => void;
  onNone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="multiselect" ref={ref}>
      <button className="multiselect-btn" onClick={() => setOpen((v) => !v)}>
        {label}
        {selected.size > 0 ? ` (${selected.size})` : ""} ▾
      </button>
      {open && (
        <div className="multiselect-panel">
          <div className="multiselect-actions">
            <button className="link-btn" onClick={onAll}>
              all
            </button>
            <button className="link-btn" onClick={onNone}>
              none
            </button>
          </div>
          {options.map((o) => (
            <label key={o} className="multiselect-option">
              <input type="checkbox" checked={selected.has(o)} onChange={() => onToggle(o)} />
              {o}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function groupKey(row: PhaseReportRow) {
  return `${row.account_name}||${row.community_name ?? ""}`;
}
