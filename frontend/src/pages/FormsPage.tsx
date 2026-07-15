const FORM_LIST = [
  {
    key: "phase-update",
    name: "Phase Update",
    desc: "Log construction phases for the houses in a community — dropdown per lot, date-stamped.",
    href: "#/phases",
    available: true,
  },
  {
    key: "post-walk",
    name: "Post Walk Form",
    desc: "Quality walk after install: checklist, photos, pass/issues, installer correction deadline.",
    available: false,
  },
  {
    key: "service-request",
    name: "Service Request Form",
    desc: "Intake for service calls — issue type, warranty check, billable calculation.",
    available: false,
  },
  {
    key: "warranty",
    name: "Warranty Form",
    desc: "Warranty registration and claims — labor vs material windows, extended coverage.",
    available: false,
  },
  {
    key: "field-measure",
    name: "Field Measure Form",
    desc: "Record field dimensions for office verification before the supplier order goes out.",
    available: false,
  },
];

export default function FormsPage() {
  return (
    <div>
      <div className="page-head">
        <h2>Forms</h2>
      </div>
      <div className="report-list">
        {FORM_LIST.map((f) => (
          <div key={f.key} className={`card report-card ${f.available ? "" : "planned"}`}>
            <div>
              <h3>{f.name}</h3>
              <p className="muted">{f.desc}</p>
            </div>
            {f.available ? (
              <a className="report-open" href={f.href}>
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
