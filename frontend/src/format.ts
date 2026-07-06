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
