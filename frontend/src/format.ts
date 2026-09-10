// Brian's standing preference: dates display as m/d/yy (e.g. 7/6/26).
// Parse the ISO string directly — new Date("yyyy-mm-dd") shifts by timezone.
// Phones display as xxx-xxx-xxxx regardless of how they were entered.
export function fmtPhone(raw: string | null | undefined): string {
  if (!raw) return "—";
  const digits = raw.replace(/\D/g, "");
  const ten = digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
  if (ten.length === 10) return `${ten.slice(0, 3)}-${ten.slice(3, 6)}-${ten.slice(6)}`;
  return raw; // partial/odd numbers show as typed rather than mangled
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("T")[0].split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${m}/${d}/${String(y).padStart(4, "0").slice(2)}`;
}


// Values that arrive as opaque strings from an API can still BE dates. The
// report shows CabinetTron, tracker and Smartsheet values side by side and any
// of them may hold an ISO date, so format what looks like one and leave the
// rest alone. Anchored so "4.0-Punch" and "2026 Rebate" are never mistaken for
// dates.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ]|$)/;

export function fmtMaybeDate(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  return ISO_DATE.test(text) ? fmtDate(text) : text;
}

// Excel exports numeric cells as floats, so a lot number arrives as "1189.0"
// and a lot named "0004" keeps its padding. Show the number people actually
// use, without touching genuinely alphanumeric lots like A027 or 24B.
export function fmtLot(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value).trim();
  const m = /^(\d+)(?:\.0+)?$/.exec(text);
  return m ? String(Number(m[1])) : text;
}