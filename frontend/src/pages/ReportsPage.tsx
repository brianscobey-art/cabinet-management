import { useEffect, useMemo, useRef, useState } from "react";
import {
  DomoPLReport,
  InstallWeekRow,
  JobPLReport,
  NeedsOrderRow,
  OpenPOReport,
  OpenServiceRow,
  OtherLaborReport,
  PhaseReportRow,
  ReportInfo,
  RevenueGroup,
  StatusSummaryRow,
  getDomoBuilders,
  getDomoPL,
  getInstallWeek,
  getJobPL,
  getNeedsOrdering,
  getOpenPO,
  getOpenService,
  getOtherLabor,
  getPhaseReport,
  getPoStatus,
  getReportsList,
  getRevenueBuilder,
  getRevenueSalesperson,
  openDocument,
  refreshDomoPL,
  refreshJobPL,
} from "../api";
import { fmtDate } from "../format";
import ManagerReportView from "./ManagerReport";

const money = (v: number) =>
  `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const CATEGORY_ORDER = ["Accounting", "Operations", "Sales"];

function categorize(reports: ReportInfo[]): { category: string; reports: ReportInfo[] }[] {
  const seen = new Set<string>();
  const order = [...CATEGORY_ORDER, ...reports.map((r) => r.category)].filter(
    (c) => !seen.has(c) && seen.add(c)
  );
  return order
    .map((category) => ({ category, reports: reports.filter((r) => r.category === category) }))
    .filter((g) => g.reports.length > 0);
}

function ReportsIndex({ reports }: { reports: ReportInfo[] }) {
  const groups = categorize(reports);
  return (
    <div>
      <div className="page-head">
        <h2>Reports</h2>
      </div>
      {groups.map((g) => (
        <section key={g.category} className="report-category">
          <h3 className="report-category-head">{g.category}</h3>
          <div className="report-list">
            {g.reports.map((r) => (
              <a key={r.key} className="card report-card" href={`#/reports/${r.key}`}>
                <div>
                  <h3>{r.name}</h3>
                  <p className="muted">{r.description}</p>
                </div>
                <span className="report-open">Open →</span>
              </a>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export default function ReportsPage({ hash }: { hash: string }) {
  const [reports, setReports] = useState<ReportInfo[]>([]);
  const key = hash.replace(/^#\/reports\/?/, "");

  useEffect(() => {
    getReportsList().then(setReports).catch(() => {});
  }, []);

  const current = reports.find((r) => r.key === key);
  const groups = categorize(reports);

  if (!key) return <ReportsIndex reports={reports} />;

  return (
    <div>
      <div className="page-sticky no-print">
        <div className="page-head">
          <h2>
            <a className="crumb" href="#/reports">
              Reports
            </a>
            {current ? ` · ${current.category}` : ""}
          </h2>
          <select
            className="report-picker"
            value={key}
            onChange={(e) => {
              window.location.hash = `#/reports/${e.target.value}`;
            }}
          >
            {groups.map((g) => (
              <optgroup key={g.category} label={g.category}>
                {g.reports.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
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
      {key === "open-service" && <OpenServiceView />}
      {key === "job-pl" && <JobPLView />}
      {key === "other-labor" && <OtherLaborView />}
      {key === "domo-pl" && <DomoPLView />}
      {key === "manager" && <ManagerReportView />}
    </div>
  );
}

const signed = (v: number) =>
  `${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
const pct = (v: number | null) => (v != null ? `${v}%` : "—");

function JobPLPrintSummary({ data }: { data: JobPLReport }) {
  const byBuilder = useMemo(() => {
    const m = new Map<
      string,
      { count: number; revenue: number; cost: number; other: number; margin: number }
    >();
    for (const r of data.rows) {
      const g = m.get(r.account_name) || { count: 0, revenue: 0, cost: 0, other: 0, margin: 0 };
      g.count += 1;
      g.revenue += r.revenue;
      g.cost += r.product_cost + r.labor_cost;
      g.other += r.other_labor_net;
      g.margin += r.margin;
      m.set(r.account_name, g);
    }
    return [...m.entries()]
      .map(([name, v]) => ({ name, ...v }))
      .sort((a, b) => b.revenue - a.revenue);
  }, [data]);

  return (
    <div className="print-only pl-summary">
      <div className="print-title">
        Carter Kitchen and Bath — Job Cost P&amp;L Summary — {fmtDate(new Date().toISOString())}
      </div>
      <div className="pl-topline">
        <div>
          <span className="pl-big">{money(data.total_revenue)}</span>
          <span>Revenue</span>
        </div>
        <div>
          <span className="pl-big">{money(data.total_cost)}</span>
          <span>Product + C9009 cost</span>
        </div>
        <div>
          <span className="pl-big">{signed(data.total_other_labor_net)}</span>
          <span>Other cabinet labor</span>
        </div>
        <div>
          <span className="pl-big">{money(data.total_margin)}</span>
          <span>All-in margin{data.margin_pct != null ? ` (${data.margin_pct}%)` : ""}</span>
        </div>
        <div>
          <span className="pl-big">{data.count}</span>
          <span>Houses</span>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Builder</th>
            <th className="num">Houses</th>
            <th className="num">Revenue</th>
            <th className="num">Product + C9009 cost</th>
            <th className="num">Other labor</th>
            <th className="num">All-in margin</th>
            <th className="num">GM %</th>
          </tr>
        </thead>
        <tbody>
          {byBuilder.map((b) => (
            <tr key={b.name}>
              <td>{b.name}</td>
              <td className="num">{b.count}</td>
              <td className="num">{money(b.revenue)}</td>
              <td className="num">{money(b.cost)}</td>
              <td className="num">{signed(b.other)}</td>
              <td className="num">{money(b.margin)}</td>
              <td className="num">{b.revenue ? `${((b.margin / b.revenue) * 100).toFixed(1)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>
              <strong>Total</strong>
            </td>
            <td className="num">
              <strong>{data.count}</strong>
            </td>
            <td className="num">
              <strong>{money(data.total_revenue)}</strong>
            </td>
            <td className="num">
              <strong>{money(data.total_cost)}</strong>
            </td>
            <td className="num">
              <strong>{signed(data.total_other_labor_net)}</strong>
            </td>
            <td className="num">
              <strong>{money(data.total_margin)}</strong>
            </td>
            <td className="num">
              <strong>{data.margin_pct != null ? `${data.margin_pct}%` : ""}</strong>
            </td>
          </tr>
        </tfoot>
      </table>
      <p className="pl-note">
        All-in margin = cabinet product + C9009 install labor + the net of every other real cabinet labor
        code (folded in per your direction). {data.with_other_labor} of {data.count} houses carry such labor.
        {data.drh_po_count > 0
          ? ` For ${data.drh_po_count} DR Horton houses, revenue is the actual DRH PO amount paid (with check number) from the DRH Combined report, in lieu of Domo product sales.`
          : ""}{" "}
        A further {signed(data.total_wash_labor_net)} of C9091 install-sales overhead and C9002 labor rebill
        is parked on these jobs by miscoding; it nets to ~$0 company-wide and is excluded here as
        non-cabinet cost.
      </p>
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
              {data.drh_po_count > 0 ? ` · ${data.drh_po_count} using DRH PO revenue` : ""}
            </span>
          )}
          {data && (
            <span className="muted" style={{ marginLeft: "0.5rem" }}>
              {data.updated_at ? `updated ${fmtDate(data.updated_at)}` : "no data pulled yet"}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {data && data.count > 0 && (
            <button onClick={() => window.print()}>🖨 Print Summary</button>
          )}
          <button onClick={update} disabled={busy}>
            {busy ? "⟳ Updating…" : "⟳ Update from Domo"}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {data && data.count === 0 && (
        <p className="muted">
          No Domo cost data yet. Log into Domo, run the pull, then click “Update from Domo”.
        </p>
      )}

      {data && data.count > 0 && <JobPLPrintSummary data={data} />}

      {data && data.count > 0 && (
        <div className="table-wrap no-print">
          <table>
            <thead>
              <tr>
                <th>Job code</th>
                <th>Builder</th>
                <th>Community</th>
                <th>Lot</th>
                <th>G / I code</th>
                <th className="num">Revenue</th>
                <th>Revenue basis</th>
                <th className="num">Product cost</th>
                <th className="num">C9009 cost</th>
                <th className="num">Other labor</th>
                <th className="num">Margin</th>
                <th className="num">GM %</th>
                <th className="num">Overhead (excl)</th>
                <th>Non-C9009 codes</th>
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
                  <td>
                    {r.revenue_source === "DRH PO" ? (
                      <span
                        title={
                          `DRH PO ${r.builder_po ?? ""}` +
                          (r.po_check_number ? ` · check #${r.po_check_number}` : "") +
                          (r.po_paid_date ? ` · paid ${fmtDate(r.po_paid_date)}` : "")
                        }
                      >
                        DRH PO{r.po_check_number ? ` · chk ${r.po_check_number}` : ""}
                      </span>
                    ) : (
                      <span className="muted">Domo</span>
                    )}
                  </td>
                  <td className="num">{money(r.product_cost)}</td>
                  <td className="num">{money(r.labor_cost)}</td>
                  <td className="num">{r.other_labor_net ? signed(r.other_labor_net) : "—"}</td>
                  <td className="num">{money(r.margin)}</td>
                  <td className="num">{r.margin_pct != null ? `${r.margin_pct}%` : "—"}</td>
                  <td className="num muted" title={r.wash_labor_codes ?? ""}>
                    {r.wash_labor_net ? signed(r.wash_labor_net) : "—"}
                  </td>
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
                <td colSpan={3} className="num" />
                <td className="num">
                  <strong>{signed(data.total_other_labor_net)}</strong>
                </td>
                <td className="num">
                  <strong>{money(data.total_margin)}</strong>
                </td>
                <td className="num">
                  <strong>{data.margin_pct != null ? `${data.margin_pct}%` : ""}</strong>
                </td>
                <td className="num">
                  <strong>{signed(data.total_wash_labor_net)}</strong>
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

function OtherLaborView() {
  const [data, error] = useReport<OtherLaborReport>(getOtherLabor);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (data.count === 0)
    return <p className="muted">No houses carry labor on codes other than C9009 yet. Update the Job Cost P&amp;L first.</p>;
  return (
    <>
      <div className="page-head no-print" style={{ justifyContent: "space-between" }}>
        <span className="report-total">
          {data.count} houses · other cabinet labor {signed(data.total_other_labor_net)} · all-in margin{" "}
          {money(data.total_all_in_margin)}
        </span>
        <button onClick={() => window.print()}>🖨 Print</button>
      </div>
      <div className="print-title print-only">
        Carter Kitchen and Bath — Labor on Non-C9009 Codes — {fmtDate(new Date().toISOString())}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job code</th>
              <th>Builder</th>
              <th>Community</th>
              <th>I-code</th>
              <th className="num">C9009 margin</th>
              <th className="num">Other labor (net)</th>
              <th className="num">All-in margin</th>
              <th>Codes</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.job_id} className={r.other_labor_net < 0 ? "flag-row" : ""}>
                <td>
                  <a href={`#/jobs/${r.job_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                </td>
                <td>{r.account_name}</td>
                <td>{r.community_name ?? "—"}</td>
                <td>{r.i_code ?? "—"}</td>
                <td className="num">{money(r.c9009_margin)}</td>
                <td className="num">{signed(r.other_labor_net)}</td>
                <td className="num">{money(r.all_in_margin)}</td>
                <td>{r.other_labor_codes ?? ""}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4}>
                <strong>Total</strong>
              </td>
              <td className="num">
                <strong>{money(data.total_c9009_margin)}</strong>
              </td>
              <td className="num">
                <strong>{signed(data.total_other_labor_net)}</strong>
              </td>
              <td className="num">
                <strong>{money(data.total_all_in_margin)}</strong>
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="pl-note">
        "Other labor (net)" is the net of real non-C9009 cabinet labor codes (e.g. C9018 punch, C9019 parts),
        folded into the all-in margin.
      </p>
    </>
  );
}

const DOMO_MODES = [
  { key: "window", label: "Date window" },
  { key: "quarter", label: "By quarter" },
  { key: "half", label: "By half-year" },
  { key: "ytd", label: "Year to date" },
  { key: "yoy", label: "Year over year" },
];
const YEARS = [2026, 2025, 2024];

function DomoPLView() {
  const [mode, setMode] = useState("window");
  const [builder, setBuilder] = useState("");
  const [job, setJob] = useState("");
  const [year, setYear] = useState(2026);
  const [quarter, setQuarter] = useState(1);
  const [half, setHalf] = useState(1);
  const [start, setStart] = useState("2026-01-01");
  const [end, setEnd] = useState("2026-07-16");
  const [builders, setBuilders] = useState<string[]>([]);
  const [data, setData] = useState<DomoPLReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    getDomoBuilders().then(setBuilders).catch(() => {});
  }, []);

  function run() {
    setError("");
    const params: Record<string, string> = { mode };
    if (builder) params.builder = builder;
    if (job.trim()) params.job = job.trim();
    if (mode === "window") {
      params.start = start;
      params.end = end;
    } else {
      params.year = String(year);
      if (mode === "quarter") params.quarter = String(quarter);
      if (mode === "half") params.half = String(half);
    }
    getDomoPL(params).then(setData).catch((e) => setError(e.message));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(run, [mode, builder, job, year, quarter, half, start, end]);

  async function update() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const res = await refreshDomoPL();
      if (res.error) {
        setError(String(res.error));
      } else if (res.houses != null) {
        const skipped = Number(res.skipped_no_date ?? 0);
        setNotice(
          `Calculated from the last Domo cost pull: ${res.houses} houses` +
            (skipped ? ` · ${skipped} without an install date were skipped` : "")
        );
      } else {
        setNotice(
          `Imported ${res.inserted ?? 0} transactions from ${res.file ?? "export"} (${res.matched ?? 0} matched)`
        );
      }
      getDomoBuilders().then(setBuilders).catch(() => {});
      run();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="filters no-print">
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          {DOMO_MODES.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
        <select value={builder} onChange={(e) => setBuilder(e.target.value)}>
          <option value="">All builders</option>
          {builders.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
        <input
          placeholder="Job code (optional)"
          value={job}
          onChange={(e) => setJob(e.target.value)}
          style={{ width: "10rem" }}
        />
        {mode === "window" && (
          <>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
            <span className="muted" style={{ alignSelf: "center" }}>
              to
            </span>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </>
        )}
        {mode !== "window" && (
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        )}
        {mode === "quarter" && (
          <select value={quarter} onChange={(e) => setQuarter(Number(e.target.value))}>
            {[1, 2, 3, 4].map((q) => (
              <option key={q} value={q}>
                Q{q}
              </option>
            ))}
          </select>
        )}
        {mode === "half" && (
          <select value={half} onChange={(e) => setHalf(Number(e.target.value))}>
            <option value={1}>H1 (Jan–Jun)</option>
            <option value={2}>H2 (Jul–Dec)</option>
          </select>
        )}
        <span style={{ flex: 1 }} />
        {data && !data.no_data && (
          <button onClick={() => window.print()}>🖨 Print</button>
        )}
        <button className="primary" onClick={update} disabled={busy}>
          {busy ? "⟳ Calculating…" : "⟳ Calculate from last Domo pull"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {data && data.no_data && <p className="muted">{data.note}</p>}
      {data && !data.no_data && <DomoPLResult data={data} builder={builder} job={job} />}
      {data && !data.no_data && data.note && <p className="pl-note no-print">{data.note}</p>}
      {data && (
        <p className="muted no-print">
          {data.updated_at ? `data updated ${fmtDate(data.updated_at)}` : ""}
        </p>
      )}
    </>
  );
}

function DomoPLResult({ data, builder, job }: { data: DomoPLReport; builder: string; job: string }) {
  const scope = job.trim() ? `Job ${job.trim()}` : builder || "All builders";
  const groupLabel = job.trim() ? "Job" : builder ? "Job" : "Builder";
  const yoy = data.periods.length > 1;
  return (
    <>
      <div className="print-title print-only">
        Carter Kitchen and Bath — Domo P&amp;L ({scope}) — {data.periods.map((p) => p.label).join(" vs ")}
      </div>
      <div className="pl-topline">
        {data.periods.map((p, i) => (
          <div key={p.key}>
            <span className="pl-big">{money(data.totals[i]?.margin ?? 0)}</span>
            <span>
              {p.label} margin{data.totals[i]?.margin_pct != null ? ` (${data.totals[i].margin_pct}%)` : ""}
            </span>
          </div>
        ))}
        <div>
          <span className="pl-big">{money(data.totals[0]?.revenue ?? 0)}</span>
          <span>Revenue {data.periods[0]?.label}</span>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{groupLabel}</th>
              {data.periods.map((p) => (
                <th key={p.key} className="num" colSpan={yoy ? 2 : 4}>
                  {p.label}
                </th>
              ))}
              {yoy && <th className="num">Δ margin</th>}
            </tr>
            <tr>
              <th />
              {data.periods.map((p) =>
                yoy ? (
                  <>
                    <th key={p.key + "r"} className="num">
                      Revenue
                    </th>
                    <th key={p.key + "m"} className="num">
                      Margin
                    </th>
                  </>
                ) : (
                  <>
                    <th key={p.key + "r"} className="num">
                      Revenue
                    </th>
                    <th key={p.key + "o"} className="num">
                      Other labor
                    </th>
                    <th key={p.key + "m"} className="num">
                      Margin
                    </th>
                    <th key={p.key + "p"} className="num">
                      GM %
                    </th>
                  </>
                )
              )}
              {yoy && <th />}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.label} className={(row.cells[0]?.margin ?? 0) < 0 ? "flag-row" : ""}>
                <td>
                  {row.label}
                  {row.sublabel ? <span className="muted"> · {row.sublabel}</span> : ""}
                </td>
                {row.cells.map((c, i) =>
                  yoy ? (
                    <>
                      <td key={i + "r"} className="num">
                        {money(c.revenue)}
                      </td>
                      <td key={i + "m"} className="num">
                        {money(c.margin)}
                      </td>
                    </>
                  ) : (
                    <>
                      <td key={i + "r"} className="num">
                        {money(c.revenue)}
                      </td>
                      <td key={i + "o"} className="num">
                        {c.other_labor_net ? signed(c.other_labor_net) : "—"}
                      </td>
                      <td key={i + "m"} className="num">
                        {money(c.margin)}
                      </td>
                      <td key={i + "p"} className="num">
                        {pct(c.margin_pct)}
                      </td>
                    </>
                  )
                )}
                {yoy && (
                  <td className="num">
                    {signed((row.cells[0]?.margin ?? 0) - (row.cells[1]?.margin ?? 0))}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>
                <strong>Total</strong>
              </td>
              {data.totals.map((c, i) =>
                yoy ? (
                  <>
                    <td key={i + "r"} className="num">
                      <strong>{money(c.revenue)}</strong>
                    </td>
                    <td key={i + "m"} className="num">
                      <strong>{money(c.margin)}</strong>
                    </td>
                  </>
                ) : (
                  <>
                    <td key={i + "r"} className="num">
                      <strong>{money(c.revenue)}</strong>
                    </td>
                    <td key={i + "o"} className="num">
                      <strong>{signed(c.other_labor_net)}</strong>
                    </td>
                    <td key={i + "m"} className="num">
                      <strong>{money(c.margin)}</strong>
                    </td>
                    <td key={i + "p"} className="num">
                      <strong>{pct(c.margin_pct)}</strong>
                    </td>
                  </>
                )
              )}
              {yoy && (
                <td className="num">
                  <strong>{signed((data.totals[0]?.margin ?? 0) - (data.totals[1]?.margin ?? 0))}</strong>
                </td>
              )}
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="pl-note">
        Margin = product + C9009 install labor + real non-C9009 cabinet labor. C9091/C9002 overhead &amp;
        rebill are excluded. Figures are Domo actuals for the period shown.
      </p>
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

function OpenServiceView() {
  const [rows, error] = useReport<OpenServiceRow[]>(getOpenService);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <>
      <p className="report-total">
        {rows.length} open service request{rows.length === 1 ? "" : "s"}
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
              <th>Request</th>
              <th>Status</th>
              <th>Material</th>
              <th>Created</th>
              <th>Scheduled</th>
              <th className="num">Open / total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.sr_id}>
                <td>
                  <a href={`#/service/${r.sr_id}`}>{r.job_code ?? `#${r.job_id}`}</a>
                </td>
                <td>{r.account_name}</td>
                <td>{r.community_name ?? "—"}</td>
                <td>{r.lot_number ?? "—"}</td>
                <td>{r.address}</td>
                <td>{r.title ?? "—"}</td>
                <td>{r.status}</td>
                <td>{r.material_status ?? "—"}</td>
                <td>{fmtDate(r.created_at)}</td>
                <td>{r.scheduled_date ? fmtDate(r.scheduled_date) : "—"}</td>
                <td className="num">
                  {r.open_lines} / {r.total_lines}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={11} className="muted">
                  No open service requests.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
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
