import { useState } from "react";
import { CHANGELOG } from "../changelog";
import { User } from "../api";

interface Topic {
  q: string;
  a: string;
  adminOnly?: boolean;
}

const TOPICS: Topic[] = [
  {
    q: "Getting around",
    a:
      "Signing in lands you on the COAST menu — the five app tiles. Click a tile to open an app. From anywhere, click the Carter logo (top-left) or the ⠿ button to come back to this menu. On a phone, use your browser's Share → Add to Home Screen to install it like an app.",
  },
  {
    q: "The five apps (COAST)",
    a:
      "Cabinetron — the cabinet database: jobs, POs, houses, communities, reports. Optimus — ordering: trim a priced job to exactly what a house needs. Autobot — service-tech scheduling & routing. Sterling (pricing) and Tailgate (installer scheduling) are coming soon.",
  },
  {
    q: "Jobs",
    a:
      "The Jobs tab lists your houses. Pick National or Local, then a builder, division, and community to narrow the list. Click a job to see every room's cabinet spec, hardware, documents, quotes, field measure, and service history. Use the search box to jump to a job by code or address.",
  },
  {
    q: "Updating the data",
    a:
      "The ⟳ Update button pulls the latest job statuses and install dates from the 3.0 Sales Tracker and the Vendor Suite / Century reports. Note: in the cloud this only works once the daily report files are being uploaded to storage (the R2 step). Until then it will say 'no file found' — that's expected, not an error.",
  },
  {
    q: "Ordering board",
    a:
      "The Ordering tab tracks each national job through the 4 steps: 1) POs & Selection File, 2) Orders & Layouts, 3) SOs & Order Comparison, 4) POs Attached. Click a step to mark it done (it stamps the date). Closed jobs are hidden by default.",
  },
  {
    q: "Phases",
    a:
      "The Phases tab shows houses by builder and community with their current construction phase. Field crews can update a house's phase from the dropdown; every change is logged with who and when. Finished/void jobs and anything past punch are hidden.",
  },
  {
    q: "Forms & Service Requests",
    a:
      "The Forms tab creates a Service Request for a house — pick the builder, community, and house, then add the parts and the punch list. You can print it or download the Excel version. There's one service request per house so everything for that home stays together.",
  },
  {
    q: "Reports",
    a:
      "The Reports tab has open-PO load, revenue by builder/salesperson, install-by-week, job P&L, and the open-service list. Financial reports keep closed jobs (for the dollars) but exclude voided ones; the operational tabs hide closed and void.",
  },
  {
    q: "Adding users & access levels",
    adminOnly: true,
    a:
      "The Users tab (admins only) is where you add people and set what they can do. Access levels: Admin (everything, incl. users), Sales (create & edit jobs/quotes/orders), Field & Installer coordinator (view all + log phases), Inspector (view-only), Service tech (Autobot only). You can change anyone's level, disable a departed employee, or reset a password anytime.",
  },
  {
    q: "How a new person signs in",
    adminOnly: true,
    a:
      "If email invites are connected, adding a user emails them a link to set their own password — they never get a password from you, and there's nothing to change on first login. If invites aren't set up, you set a temporary password and share it; they can keep it or you can reset it. You can resend an invite anytime from the Users tab.",
  },
];

export default function HelpPage({ me }: { me: User }) {
  const [open, setOpen] = useState<number | null>(0);
  const isAdmin = me.role === "admin";
  const topics = TOPICS.filter((t) => !t.adminOnly || isAdmin);

  return (
    <div>
      <div className="page-head">
        <h2>Help &amp; Training</h2>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>What's new</h3>
        <ul className="changelog">
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

      <div className="card" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>How-to &amp; FAQ</h3>
        {topics.map((t, i) => (
          <div key={i} style={{ borderTop: i ? "1px solid #eee" : undefined, padding: "8px 0" }}>
            <button
              className="link-btn"
              style={{ fontWeight: 600, fontSize: "1rem" }}
              onClick={() => setOpen(open === i ? null : i)}
            >
              {open === i ? "▾ " : "▸ "}
              {t.q}
            </button>
            {open === i && <p style={{ margin: "6px 0 2px 18px" }}>{t.a}</p>}
          </div>
        ))}
      </div>

      <p className="muted" style={{ marginTop: "1rem" }}>
        Missing something, or want a step explained better? Tell Brian and it'll get added here.
      </p>
    </div>
  );
}
