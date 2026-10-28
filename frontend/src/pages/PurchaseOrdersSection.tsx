import { Fragment, useEffect, useState } from "react";
import { getJobPurchaseOrders, JobPurchaseOrders } from "../api";
import { fmtDate } from "../format";

const money = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// Every PO on the job (Brian 10/28/26): our POs from the tracker's PO Tracking
// sheet, each with its DOMO receipt -- or how late it is.
export default function PurchaseOrdersSection({ jobId }: { jobId: number }) {
  const [data, setData] = useState<JobPurchaseOrders | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getJobPurchaseOrders(jobId).then(setData).catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return null;
  const pos = data.purchase_orders;

  return (
    <>
      <h3 className="kb-head">Purchase orders</h3>
      <p className="muted" style={{ margin: "0 0 0.5rem" }}>
        Builder PO {data.builder_po ?? "—"} · {money(data.po_amount)}
        {data.cabinet_po ? ` · Cabinet PO ${data.cabinet_po}` : ""}
        {pos.length > 0 && ` · received ${money(data.received_cost)} landed (DOMO)`}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Our PO #</th>
              <th>Vendor</th>
              <th>Product</th>
              <th>Ordered</th>
              <th>Due</th>
              <th className="num">PO cost</th>
              <th>Received</th>
              <th>Receipt #</th>
              <th className="num">Supplier cost</th>
              <th className="num">Landed cost</th>
            </tr>
          </thead>
          <tbody>
            {pos.map((p) => {
              const recs = p.receipts.length ? p.receipts : [null];
              return (
                <Fragment key={p.our_po}>
                  {recs.map((r, i) => (
                    <tr key={`${p.our_po}-${r?.receipt_number ?? i}`}>
                      <td>{i === 0 ? p.our_po : ""}</td>
                      <td>{i === 0 ? p.vendor ?? "—" : ""}</td>
                      <td>{i === 0 ? p.product ?? "—" : ""}</td>
                      <td>{i === 0 ? fmtDate(p.order_date) : ""}</td>
                      <td>{i === 0 ? fmtDate(p.due_date) : ""}</td>
                      <td className="num">{i === 0 ? money(p.cost) : ""}</td>
                      <td>
                        {r ? (
                          fmtDate(r.receipt_date)
                        ) : p.days_overdue ? (
                          <span className="error">{p.days_overdue}d overdue</span>
                        ) : (
                          <span className="muted">awaiting</span>
                        )}
                      </td>
                      <td>{r?.receipt_number ?? ""}</td>
                      <td className="num">{r ? money(r.supplier_cost) : ""}</td>
                      <td className="num">{r ? money(r.landed_cost) : ""}</td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
            {pos.length === 0 && (
              <tr>
                <td colSpan={10} className="muted">
                  No POs on the tracker's PO Tracking sheet for this job yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
