/** The COAST suite launcher — lands here after login. Five apps, one operation:
 * CabinetTron (jobs), Optimus (ordering), Autobot (service routing), Sterling
 * (pricing — the standalone Sterling app on :8010), Tailgate (coming). */

const TILE = 64; // icon design space

function CabinetTronIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#125952" />
      <rect x="14" y="12" width="36" height="40" rx="2" fill="none" stroke="#fff" strokeWidth="3.5" />
      <line x1="32" y1="12" x2="32" y2="52" stroke="#fff" strokeWidth="3.5" />
      <circle cx="26.5" cy="32" r="2.6" fill="#568c8c" />
      <circle cx="37.5" cy="32" r="2.6" fill="#568c8c" />
    </svg>
  );
}

function OptimusIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#125952" />
      <path d="M32 12 L50 21 L50 41 L32 50 L14 41 L14 21 Z" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M14 21 L32 30 L50 21 M32 30 L32 50" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M37 17.5 L27 12.7" stroke="#568c8c" strokeWidth="3.5" strokeLinecap="round" />
    </svg>
  );
}

function AutobotIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#125952" />
      <path d="M14 40 C14 24, 50 24, 50 40" fill="none" stroke="#fff" strokeWidth="4" strokeLinecap="round" strokeDasharray="6 5" />
      <rect x="27" y="40" width="10" height="8" fill="#fff" />
      <circle cx="14" cy="40" r="4" fill="#568c8c" />
      <circle cx="50" cy="40" r="4" fill="#568c8c" />
      <circle cx="32" cy="28" r="4" fill="#568c8c" />
    </svg>
  );
}

function SterlingIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#125952" />
      <path d="M12 30 L30 12 L50 12 L50 32 L32 50 Z" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <circle cx="42" cy="20" r="3.2" fill="#568c8c" />
      <path d="M31 27.5 c-4 0 -4 5 0 5 c4 0 4 5 0 5 m0 -12.5 v-2 m0 16.5 v-2" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

function TailgateIcon() {
  return (
    <svg viewBox={`0 0 ${TILE} ${TILE}`}>
      <rect width="64" height="64" rx="14" fill="#125952" />
      <path d="M12 22 H38 V40 H12 Z" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <path d="M38 28 H48 L52 34 V40 H38" fill="none" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" />
      <circle cx="21" cy="43" r="4" fill="#568c8c" />
      <circle cx="45" cy="43" r="4" fill="#568c8c" />
      <line x1="38" y1="24" x2="38" y2="18" stroke="#568c8c" strokeWidth="3" strokeLinecap="round" />
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
