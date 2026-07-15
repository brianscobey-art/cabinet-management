import { useEffect, useMemo, useRef, useState } from "react";
import {
  InstallWeekRow,
  JobPLReport,
  NeedsOrderRow,
  OpenPOReport,
  PhaseReportRow,
  ReportInfo,
  RevenueGroup,
  StatusSummaryRow,
  getInstallWeek,
  getJobPL,
  getNeedsOrdering,
  getOpenPO,
  getPhaseReport,
  getPoStatus,
  getReportsList,
  getRevenueBuilder,
  getRevenueSalesperson,
  openDocument,
  refreshJobPL,
} from "../api";
import { fmtDate } from "../format";

const money = (v: number) =>
  `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function ReportsPage({ hash }: { hash: string }) {
  const [reports, setReports] = useState<ReportInfo[]>([]);
  const key = hash.replace(/^#\/reports\/?/, "") || "phases";

  useEffect(() => {
    getReportsList().then(setReports).catch(() => {});
  }, []);

  const current = reports.find((r) => r.key === key);

  return (
    <div>
      <div className="page-sticky no-print">
        <div className="page-head">
          <h2>Reports</h2>
          <select
            className="report-picker"
            value={key}
            onChange={(e) => {
              window.location.hash = `#/reports/${e.target.value}`;
            }}
          >
            {reports.map((r) => (
              <option key={r.key} value={r.key}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        {current && <p className="muted report-desc">{current.description}</p>}
      </div>

      {key === "phases" && <PhaseReport />}
      {key === "open-po" && <OpenPOReportView />}
      {key === "po-status" && <PoStatusView />}
      {key === "revenue-builder" && <RevenueBuilderView />}
      {key === "revenue-salesperson" && <RevenueSalespersonView />}
      {key === "install-week" && <InstallWeekView />}
      {key === "unordered" && <NeedsOrderingView />}
      {key === "job-pl" && <JobPLView />}
    </div>
  );
}

function JobPLView() {
  const [data, setData] = useState<JobPLReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const load = () => getJobPL().then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function update() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const res = await refreshJobPL();
      if (res.error) setError(String(res.error));
      else setNotice(`Updated from ${res.file ?? "Domo export"}: ${res.matched ?? 0} jobs matched`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head no-print" style={{ justifyContent: "space-between" }}>
        <div>
          {data && data.count > 0 && (
            <span className="report-total">
              {data.count} houses · Revenue {money(data.total_revenue)} · Margin {money(data.total_margin)}
              {data.margin_pct != null ? ` (${data.margin_pct}%)` : ""}
              {data.with_other_labor > 0 ? ` · ${data.with_other_labor} with non-C9009 labor` : ""}
            </span>
          )}
          {data && (
            <span className="muted" style={{ marginLeft: "0.5rem" }}>
              {data.updated_at ? `updated ${fmtDate(data.updated_at)}` : "no data pulled yet"}
            </span>
          )}
        </div>
        <button onClick={update} disabled={busy}>
          {busy ? "⟳ Updating…" : "⟳ Update from Domo"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {data && data.count === 0 && (
        <p className="muted">
          No Domo cost data yet. Log into Domo, run the pull, then click “Update from Domo”.
        </p>
      )}
      {data && data.count > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job code</th>
                <th>Builder</th>
                <th>Community</th>
                <th>Lot</th>
                <th>G / I code</th>
                <th className="num">Revenue</th>
                <th className="num">Product cost</th>
                <th className="num">Labor cost</th>
                <th className="num">Margin</th>
                <th className="num">GM %</th>
                <th>Non-C9009 labor</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.job_id} className={r.other_labor_codes ? "flag-row" : ""}>
                  <td>
                    <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                  </td>
                  <td>{r.account_name}</td>
                  <td>{r.community_name ?? "—"}</td>
                  <td>{r.lot_number ?? "—"}</td>
                  <td>{[r.g_code, r.i_code].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="num">{money(r.revenue)}</td>
                  <td className="num">{money(r.product_cost)}</td>
                  <td className="num">{money(r.labor_cost)}</td>
                  <td className="num">{money(r.margin)}</td>
                  <td className="num">{r.margin_pct != null ? `${r.margin_pct}%` : "—"}</td>
                  <td>{r.other_labor_codes ?? ""}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={5}>
                  <strong>Total</strong>
                </td>
                <td className="num">
                  <strong>{money(data.total_revenue)}</strong>
                </td>
                <td colSpan={2} className="num" />
                <td className="num">
                  <strong>{money(data.total_margin)}</strong>
                </td>
                <td className="num">
                  <strong>{data.margin_pct != null ? `${data.margin_pct}%` : ""}</strong>
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </>
  );
}

function useReport<T>(loader: () => Promise<T>): [T | null, string] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    loader().then(setData).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [data, error];
}

function OpenPOReportView() {
  const [data, error] = useReport<OpenPOReport>(getOpenPO);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="report-total">
        {data.count} open PO{data.count === 1 ? "" : "s"} · {money(data.total_amount)}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job code</th>
              <th>Builder</th>
              <th>Community</th>
              <th>Lot</th>
              <th>Address</th>
              <th>PO #</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.job_id}>
                <td>
                  <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                </td>
                <td>{r.account_name}</td>
                <td>{r.community_name ?? "—"}</td>
                <td>{r.lot_number ?? "—"}</td>
                <td>{r.address}</td>
                <td>{r.builder_po ?? "—"}</td>
                <td className="num">{money(r.po_amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={6}>
                <strong>Total</strong>
              </td>
              <td className="num">
                <strong>{money(data.total_amount)}</strong>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </>
  );
}

function PoStatusView() {
  const [rows, error] = useReport<StatusSummaryRow[]>(getPoStatus);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  const total = rows.reduce((s, r) => s + r.total_amount, 0);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>PO status</th>
            <th className="num">Jobs</th>
            <th className="num">Total amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.po_status}>
              <td>{r.po_status}</td>
              <td className="num">{r.count}</td>
              <td className="num">{money(r.total_amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>
              <strong>All</strong>
            </td>
            <td className="num">
              <strong>{rows.reduce((s, r) => s + r.count, 0)}</strong>
            </td>
            <td className="num">
              <strong>{money(total)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function RevenueGroupView({ loader }: { loader: () => Promise<RevenueGroup[]> }) {
  const [rows, error] = useReport<RevenueGroup[]>(loader);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  const total = rows.reduce((s, r) => s + r.total_amount, 0);
  const hasSub = rows.some((r) => r.sublabel);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{hasSub ? "Builder" : "Salesperson"}</th>
            {hasSub && <th>Community</th>}
            <th className="num">Jobs</th>
            <th className="num">Revenue</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.label}</td>
              {hasSub && <td>{r.sublabel ?? "—"}</td>}
              <td className="num">{r.count}</td>
              <td className="num">{money(r.total_amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={hasSub ? 3 : 2}>
              <strong>Total</strong>
            </td>
            <td className="num">
              <strong>{money(total)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

const RevenueBuilderView = () => <RevenueGroupView loader={getRevenueBuilder} />;
const RevenueSalespersonView = () => <RevenueGroupView loader={getRevenueSalesperson} />;

function InstallWeekView() {
  const [rows, error] = useReport<InstallWeekRow[]>(getInstallWeek);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Week of</th>
            <th className="num">Installs</th>
            <th className="num">PO value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.week_start}>
              <td>{fmtDate(r.week_start)}</td>
              <td className="num">{r.count}</td>
              <td className="num">{money(r.total_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NeedsOrderingView() {
  const [rows, error] = useReport<NeedsOrderRow[]>(getNeedsOrdering);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="report-total">{rows.length} job{rows.length === 1 ? "" : "s"} scheduled without a cabinet PO</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Install</th>
              <th>Job code</th>
              <th>Builder</th>
              <th>Community</th>
              <th>Lot</th>
              <th>Address</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.job_id}>
                <td>{fmtDate(r.install_date)}</td>
                <td>
                  <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                </td>
                <td>{r.account_name}</td>
                <td>{r.community_name ?? "—"}</td>
                <td>{r.lot_number ?? "—"}</td>
                <td>{r.address}</td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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
      <div className="no-print">
        <div className="page-head" style={{ justifyContent: "flex-end" }}>
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
