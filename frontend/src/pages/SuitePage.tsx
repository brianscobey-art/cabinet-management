/** The COAST suite launcher — lands here after login. Five apps, one operation:
 * CabinetTron (jobs), Optimus (ordering), Autobot (service routing), Sterling
 * (pricing — the standalone Sterling app on :8010), Tailgate (coming). */

function CabinetTronIcon() {
  return <img src="/brand/cabinettron-icon.png" alt="CabinetTron" />;
}

function OptimusIcon() {
  return <img src="/brand/optimus-icon.png" alt="Optimus" />;
}

function AutobotIcon() {
  return <img src="/brand/autobot-icon.png" alt="Autobot" />;
}

function SterlingIcon() {
  return <img src="/brand/sterling-icon.png" alt="Sterling" />;
}

function TailgateIcon() {
  return <img src="/brand/tailgate-icon.png" alt="Tailgate" />;
}

const APPS = [
  {
    name: "CabinetTron",
    tag: "The cabinet database — jobs, POs, houses, communities",
    href: "#/jobs",
    icon: <CabinetTronIcon />,
    live: true,
  },
  {
    name: "Optimus",
    tag: "Ordering — trim a priced job to exactly what the house needs",
    href: "/ordering-platform",
    icon: <OptimusIcon />,
    live: true,
  },
  {
    name: "Autobot",
    tag: "Service tech scheduling & routing",
    href: "/autobot",
    icon: <AutobotIcon />,
    live: true,
  },
  {
    // Sterling lives inside CabinetTron (same pattern as Optimus/Autobot).
    name: "Sterling",
    tag: "Pricing",
    href: "/sterling",
    icon: <SterlingIcon />,
    live: true,
  },
  {
    name: "Tailgate",
    tag: "Installer scheduling",
    href: null,
    icon: <TailgateIcon />,
    live: false,
  },
];

export default function SuitePage() {
  return (
    <div className="suite">
      <div className="suite-head">
        <h2>
          {APPS.map((a) => (
            <span key={a.name} className="suite-letter">
              {a.name[0]}
            </span>
          ))}
        </h2>
        <p className="muted">One operation, five apps. Pick where you're working.</p>
      </div>
      <div className="suite-grid">
        {APPS.map((a) =>
          a.live ? (
            <a key={a.name} className="suite-tile" href={a.href!}>
              {a.icon}
              <b>{a.name}</b>
              <span className="muted">{a.tag}</span>
            </a>
          ) : (
            <div key={a.name} className="suite-tile soon" title="Coming soon">
              {a.icon}
              <b>{a.name}</b>
              <span className="muted">{a.tag}</span>
              <span className="suite-soon">coming soon</span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}
