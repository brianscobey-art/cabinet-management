import { useEffect, useMemo, useState } from "react";
import { Account, InstallItem, getInstalls, listAccounts, statusSlug } from "../api";
import { fmtDate } from "../format";

type View = "month" | "week" | "day";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const startOfWeek = (d: Date) => addDays(d, -d.getDay());
const sameDay = (a: Date, b: Date) => iso(a) === iso(b);

export default function SchedulePage() {
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [items, setItems] = useState<InstallItem[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountFilter, setAccountFilter] = useState("");
  const [error, setError] = useState("");

  const range = useMemo(() => {
    if (view === "month") {
      const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
      const start = startOfWeek(first);
      return { start, end: addDays(start, 41) };
    }
    if (view === "week") {
      const start = startOfWeek(anchor);
      return { start, end: addDays(start, 6) };
    }
    return { start: anchor, end: anchor };
  }, [view, anchor]);

  useEffect(() => {
    const params: Record<string, string> = { start: iso(range.start), end: iso(range.end) };
    if (accountFilter) params.account_id = accountFilter;
    getInstalls(params).then(setItems).catch((e) => setError(e.message));
  }, [range, accountFilter]);

  useEffect(() => {
    listAccounts().then(setAccounts).catch(() => {});
  }, []);

  const byDay = useMemo(() => {
    const map = new Map<string, InstallItem[]>();
    for (const item of items) {
      const list = map.get(item.install_date) ?? [];
      list.push(item);
      map.set(item.install_date, list);
    }
    return map;
  }, [items]);

  function step(direction: 1 | -1) {
    if (view === "month") setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + direction, 1));
    else setAnchor(addDays(anchor, direction * (view === "week" ? 7 : 1)));
  }

  const title =
    view === "month"
      ? `${MONTHS[anchor.getMonth()]} ${anchor.getFullYear()}`
      : view === "week"
        ? `${fmtDate(iso(startOfWeek(anchor)))} – ${fmtDate(iso(addDays(startOfWeek(anchor), 6)))}`
        : `${DOW[anchor.getDay()]} ${fmtDate(iso(anchor))}`;

  return (
    <div>
      <div className="page-sticky">
        <div className="page-head">
          <h2>Install Schedule</h2>
          <div className="cal-controls">
            <select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}>
              <option value="">All accounts</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <div className="view-toggle">
              {(["month", "week", "day"] as View[]).map((v) => (
                <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
                  {v}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="cal-nav">
          <button onClick={() => step(-1)}>←</button>
          <button onClick={() => setAnchor(new Date())}>Today</button>
          <button onClick={() => step(1)}>→</button>
          <span className="cal-title">{title}</span>
          <span className="muted">{items.length} install{items.length === 1 ? "" : "s"}</span>
          <span className="cal-legend">
            <span className="cal-chip legend-chip">ordered</span>
            <span className="cal-chip not-ordered legend-chip">not ordered</span>
          </span>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {view === "month" && <MonthGrid anchor={anchor} byDay={byDay} onDayClick={(d) => { setAnchor(d); setView("day"); }} />}
      {view === "week" && <WeekGrid anchor={anchor} byDay={byDay} onDayClick={(d) => { setAnchor(d); setView("day"); }} />}
      {view === "day" && <DayList date={anchor} items={byDay.get(iso(anchor)) ?? []} />}
    </div>
  );
}

// Cabinets are "ordered" once a PO exists — 1.5-OrdPO and beyond; 1.0–1.4 are pre-order.
const NOT_ORDERED = new Set(["1.0-Track", "1.1-PreOrd", "1.2-NdOrd", "1.3-Ord Prcss", "1.4-OrdSub"]);
const isOrdered = (item: InstallItem) => !NOT_ORDERED.has(item.status);

function Chip({ item }: { item: InstallItem }) {
  const ordered = isOrdered(item);
  return (
    <a
      className={`cal-chip ${ordered ? "" : "not-ordered"}`}
      href={`#/jobs/${item.job_id}`}
      title={`${item.address} — ${item.account_name}${item.community_name ? ` / ${item.community_name}` : ""}${
        item.salesperson ? ` — ${item.salesperson}` : ""
      } — ${ordered ? "ordered" : "NOT ordered"}`}
    >
      <span className="cal-chip-code">{item.job_code ?? item.address}</span>
      {item.salesperson && <span className="cal-chip-sales">{item.salesperson}</span>}
    </a>
  );
}

function MonthGrid({
  anchor, byDay, onDayClick,
}: {
  anchor: Date;
  byDay: Map<string, InstallItem[]>;
  onDayClick: (d: Date) => void;
}) {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const start = startOfWeek(first);
  const today = new Date();
  const cells = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  const MAX = 3;
  return (
    <div className="cal-month">
      {DOW.map((d) => (
        <div key={d} className="cal-dow">
          {d}
        </div>
      ))}
      {cells.map((d) => {
        const events = byDay.get(iso(d)) ?? [];
        return (
          <div
            key={iso(d)}
            className={`cal-cell ${d.getMonth() !== anchor.getMonth() ? "other" : ""} ${sameDay(d, today) ? "today" : ""}`}
          >
            <button className="cal-daynum" onClick={() => onDayClick(d)}>
              {d.getDate()}
            </button>
            {events.slice(0, MAX).map((e) => (
              <Chip key={e.job_id} item={e} />
            ))}
            {events.length > MAX && (
              <button className="cal-more" onClick={() => onDayClick(d)}>
                +{events.length - MAX} more
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WeekGrid({
  anchor, byDay, onDayClick,
}: {
  anchor: Date;
  byDay: Map<string, InstallItem[]>;
  onDayClick: (d: Date) => void;
}) {
  const start = startOfWeek(anchor);
  const today = new Date();
  const days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
  return (
    <div className="cal-week">
      {days.map((d) => {
        const events = byDay.get(iso(d)) ?? [];
        return (
          <div key={iso(d)} className={`cal-cell week ${sameDay(d, today) ? "today" : ""}`}>
            <button className="cal-daynum" onClick={() => onDayClick(d)}>
              {DOW[d.getDay()]} {fmtDate(iso(d))}
            </button>
            {events.map((e) => (
              <Chip key={e.job_id} item={e} />
            ))}
            {events.length === 0 && <span className="muted cal-empty">—</span>}
          </div>
        );
      })}
    </div>
  );
}

function DayList({ date, items }: { date: Date; items: InstallItem[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Job code</th>
            <th>Address</th>
            <th>Account</th>
            <th>Community</th>
            <th>Lot</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.job_id} className="clickable" onClick={() => (window.location.hash = `#/jobs/${i.job_id}`)}>
              <td>
                <a href={`#/jobs/${i.job_id}`}>{i.job_code ?? `#${i.job_id}`}</a>
              </td>
              <td>{i.address}</td>
              <td>{i.account_name}</td>
              <td>{i.community_name ?? "—"}</td>
              <td>{i.lot_number ?? "—"}</td>
              <td>
                <span className={`badge badge-${statusSlug(i.status)}`}>{i.status}</span>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                No installs scheduled for {fmtDate(iso(date))}.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
