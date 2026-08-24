// Pull the DOMO "PO Receipt List" without a developer token.
//
// WHY THIS EXISTS: Carter won't issue Brian a DOMO access token, so
// po_receipts.pull_receipts_domo() (the live server-side path) can never run.
// But DOMO's query API accepts an ordinary logged-in SESSION COOKIE, so the
// same SQL works from the browser while he is signed in.
//
// HOW TO USE
//   1. Sign in at https://carterlumber.domo.com (any page).
//   2. Open DevTools -> Console, paste this whole file, press Enter.
//   3. A green DOWNLOAD CSV button appears. CLICK IT.
//      The click matters: a page-initiated download with no user gesture is
//      blocked by Chrome and fails silently. Pasting alone does nothing.
//   4. The file lands in C:\Users\Brian SE6\Downloads, which IS
//      settings.po_receipt_folder. The "CarterKB R2 Upload" task (every 5 min)
//      ships it to R2, and the cloud's 5-minute poll imports it. No other step.
//
// The 7 aliased columns must stay exactly as-is: po_receipts.COLS matches the
// CSV header by name, and a rename silently yields all-empty rows.
(async () => {
  const ds = "1f5601ba-d9a1-4ebb-aa76-ad9c5b226ea6"; // O00021.V0 Purchase Receipt Details
  const sql =
    "SELECT `transaction number` AS `Receipt #`, MAX(`transaction date`) AS `Receipt Date`, " +
    "MAX(`pos`) AS `POS`, MAX(`supplier name title`) AS `Supplier`, " +
    "SUM(`reported cost`) AS `Supplier Cost`, SUM(`landed cost`) AS `Landed Cost`, " +
    "MAX(`order number`) AS `Order #` " +
    "FROM table WHERE `transaction code`='RE' AND `pos` LIKE '750%' " +  // RE = receipt, 750 = Dothan
    "GROUP BY `transaction number`";

  const res = await fetch(`/api/query/v1/execute/${ds}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ sql }),
  });
  if (!res.ok) throw new Error(`Domo returned ${res.status} — still signed in?`);
  const j = await res.json();

  const cols = ["Receipt #","Receipt Date","POS","Supplier","Supplier Cost","Landed Cost","Order #"];
  const esc = (v) => {
    v = v === null || v === undefined ? "" : String(v);
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  };
  const csv = [cols.join(",")].concat(j.rows.map((r) => r.map(esc).join(","))).join("\r\n");

  const d = new Date();
  const mmddyy = String(d.getMonth() + 1).padStart(2, "0") +
                 String(d.getDate()).padStart(2, "0") +
                 String(d.getFullYear()).slice(2);

  document.getElementById("__dlbtn")?.remove();
  const btn = document.createElement("a");
  btn.id = "__dlbtn";
  btn.textContent = `DOWNLOAD CSV (${j.rows.length} receipts)`;
  btn.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  btn.download = `PO Receipt List ${mmddyy}.csv`;
  btn.style.cssText =
    "position:fixed;left:400px;top:400px;z-index:2147483647;background:#125952;" +
    "color:#fff;font:bold 20px sans-serif;padding:24px 40px;border-radius:8px;" +
    "text-decoration:none;display:block;";
  document.body.appendChild(btn);
  console.log(`Ready: ${j.rows.length} receipts. Click the green button.`);
})();
