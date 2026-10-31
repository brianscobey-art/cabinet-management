/** The COAST suite launcher — lands here after login. Five apps, one operation:
 * CabinetTron (jobs), Optimus (ordering), Autobot (service routing), Sterling
 * (pricing — the standalone Sterling app on :8010), Tailgate (coming). */

const TILE = 64; // icon design space

function CabinetTronIcon() {
  return <img src="/brand/cabinettron-icon.png" alt="CabinetTron" />;
}

function OptimusIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#0E2133" />
      <path d="M32 12 L50 21 L50 41 L32 50 L14 41 L14 21 Z" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M14 21 L32 30 L50 21 M32 30 L32 50" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M37 17.5 L27 12.7" stroke="#48BEF2" strokeWidth="3.5" strokeLinecap="round" />
    </svg>
  );
}

function AutobotIcon() {
  return <img src="/brand/autobot-icon.png" alt="Autobot" />;
}

function SterlingIcon() {
  return <img src="/brand/sterling-icon.png" alt="Sterling" />;
}

function TailgateIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#0E2133" />
      <path d="M12 22 H38 V40 H12 Z" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M38 28 H48 L52 34 V40 H38" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <circle cx="21" cy="43" r="4" fill="#48BEF2" />
      <circle cx="45" cy="43" r="4" fill="#48BEF2" />
      <line x1="38" y1="24" x2="38" y2="18" stroke="#48BEF2" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
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
