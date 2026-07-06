// Brian's standing preference: dates display as m/d/yy (e.g. 7/6/26).
// Parse the ISO string directly — new Date("yyyy-mm-dd") shifts by timezone.
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("T")[0].split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${m}/${d}/${String(y).padStart(4, "0").slice(2)}`;
}
