import { FormEvent, useEffect, useState } from "react";
import {
  Order,
  Quote,
  QuoteDetail,
  acceptQuote,
  addQuoteLine,
  createOrder,
  createQuote,
  deleteQuote,
  deleteQuoteLine,
  downloadOrderFile,
  getQuote,
  listOrders,
  listQuotes,
  updateOrder,
} from "../api";

const money = (v: string) => `$${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

export default function QuotesSection({ jobId, canWrite }: { jobId: number; canWrite: boolean }) {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [openQuote, setOpenQuote] = useState<QuoteDetail | null>(null);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh(keepOpen = true) {
    const [qs, os] = await Promise.all([listQuotes(jobId), listOrders(jobId)]);
    setQuotes(qs);
    setOrders(os);
    if (keepOpen && openQuote) {
      setOpenQuote(await getQuote(openQuote.id).catch(() => null));
    }
  }

  useEffect(() => {
    refresh(false).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createQuote(jobId, newName || `Option ${String.fromCharCode(65 + quotes.length)}`);
      setNewName("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  async function handleGenerateOrder(quote: Quote) {
    setError("");
    setNotice("");
    try {
      const order = await createOrder(jobId, { quote_id: quote.id });
      const skipped = order.skipped_skus ?? [];
      setNotice(
        `Everluxe order generated${skipped.length ? ` — excluded SKUs left off the form: ${skipped.join(", ")}` : ""}`
      );
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <>
      <h3>Quotes</h3>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Scenario</th>
              <th>Status</th>
              <th>Lines</th>
              <th>List total</th>
              <th>Net total (×{quotes[0] ? Number(quotes[0].multiplier) : 0.217})</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => (
              <tr key={q.id}>
                <td>
                  <button className="link-btn" onClick={() => getQuote(q.id).then(setOpenQuote)}>
                    {q.name}
                  </button>
                </td>
                <td>
                  <span className={`badge ${q.status === "accepted" ? "badge-accepted" : ""}`}>{q.status}</span>
                </td>
                <td>{q.line_count}</td>
                <td>{money(q.list_total)}</td>
                <td>{money(q.net_total)}</td>
                <td>
                  {canWrite && q.status !== "accepted" && (
                    <>
                      <button
                        className="link-btn"
                        onClick={async () => {
                          await acceptQuote(q.id);
                          refresh();
                        }}
                      >
                        accept
                      </button>{" "}
                      <button
                        className="link-btn"
                        onClick={async () => {
                          await deleteQuote(q.id).catch((e) => setError(e.message));
                          if (openQuote?.id === q.id) setOpenQuote(null);
                          refresh();
                        }}
                      >
                        delete
                      </button>
                    </>
                  )}
                  {canWrite && q.status === "accepted" && (
                    <button className="link-btn" onClick={() => handleGenerateOrder(q)}>
                      generate Everluxe order
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {quotes.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No quotes yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {canWrite && (
        <form className="inline-form" onSubmit={handleCreate}>
          <input
            placeholder={`Scenario name (Option ${String.fromCharCode(65 + quotes.length)})`}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button type="submit">New quote</button>
        </form>
      )}

      {openQuote && (
        <QuoteLines
          quote={openQuote}
          canWrite={canWrite && openQuote.status !== "accepted"}
          onChange={() => refresh()}
          onClose={() => setOpenQuote(null)}
        />
      )}

      <h3>Orders</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Supplier</th>
              <th>PO</th>
              <th>Confirmation</th>
              <th>Shipping</th>
              <th>File</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>{o.supplier}</td>
                <td>{o.po_number ?? "—"}</td>
                <td>
                  {canWrite ? (
                    <select
                      value={o.confirmation_status}
                      onChange={async (e) => {
                        await updateOrder(o.id, { confirmation_status: e.target.value });
                        refresh();
                      }}
                    >
                      <option value="pending">pending</option>
                      <option value="confirmed">confirmed</option>
                      <option value="rejected">rejected</option>
                    </select>
                  ) : (
                    o.confirmation_status
                  )}
                </td>
                <td>
                  {canWrite ? (
                    <select
                      value={o.ship_status}
                      onChange={async (e) => {
                        await updateOrder(o.id, { ship_status: e.target.value });
                        refresh();
                      }}
                    >
                      <option value="not_shipped">not shipped</option>
                      <option value="scheduled">scheduled</option>
                      <option value="shipped">shipped</option>
                      <option value="delivered">delivered</option>
                    </select>
                  ) : (
                    o.ship_status.replace(/_/g, " ")
                  )}
                </td>
                <td>
                  {o.has_file ? (
                    <button className="link-btn" onClick={() => downloadOrderFile(o.id).catch((e) => setError(e.message))}>
                      download .xlsx
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No orders yet — accept a quote to generate one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function QuoteLines({
  quote,
  canWrite,
  onChange,
  onClose,
}: {
  quote: QuoteDetail;
  canWrite: boolean;
  onChange: () => void;
  onClose: () => void;
}) {
  const empty = { room: "", qty: "1", sku: "", product_code: "", fin_end: "", color: "", list_price: "", notes: "" };
  const [form, setForm] = useState(empty);
  const [error, setError] = useState("");
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await addQuoteLine(quote.id, {
        room: form.room || null,
        qty: Number(form.qty) || 1,
        sku: form.sku,
        product_code: form.product_code || null,
        fin_end: form.fin_end || null,
        color: form.color || null,
        list_price: form.list_price || "0",
        notes: form.notes || null,
      });
      setForm(empty);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="card">
      <div className="page-head">
        <h3>
          {quote.name} — lines {quote.status === "accepted" && <span className="badge badge-accepted">accepted</span>}
        </h3>
        <button className="link-btn" onClick={onClose}>
          close
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Room</th>
              <th>Qty</th>
              <th>SKU</th>
              <th>Product code</th>
              <th>List</th>
              <th>Net each</th>
              <th>Total</th>
              <th>Notes</th>
              {canWrite && <th />}
            </tr>
          </thead>
          <tbody>
            {quote.lines.map((l) => (
              <tr key={l.id} className={l.excluded ? "excluded-row" : ""}>
                <td>{l.room ?? "—"}</td>
                <td>{l.qty}</td>
                <td>
                  {l.sku}
                  {l.excluded && <span className="badge badge-punch">excluded</span>}
                </td>
                <td>{l.product_code ?? "—"}</td>
                <td>{money(l.list_price)}</td>
                <td>{money(l.net_each)}</td>
                <td>{money(l.total)}</td>
                <td>{l.notes ?? "—"}</td>
                {canWrite && (
                  <td>
                    <button
                      className="link-btn"
                      onClick={async () => {
                        await deleteQuoteLine(l.id);
                        onChange();
                      }}
                    >
                      remove
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {quote.lines.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No lines yet.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4} />
              <td>
                <strong>{money(quote.list_total)}</strong>
              </td>
              <td />
              <td>
                <strong>{money(quote.net_total)}</strong>
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
      {canWrite && (
        <form className="inline-form" onSubmit={submit}>
          <input placeholder="Room" value={form.room} onChange={set("room")} style={{ width: "6.5rem" }} />
          <input placeholder="Qty" type="number" min="1" value={form.qty} onChange={set("qty")} style={{ width: "4rem" }} />
          <input placeholder="SKU *" value={form.sku} onChange={set("sku")} required style={{ width: "7rem" }} />
          <input placeholder="Product code" value={form.product_code} onChange={set("product_code")} style={{ width: "7rem" }} />
          <input placeholder="List price *" type="number" step="0.01" min="0" value={form.list_price} onChange={set("list_price")} required style={{ width: "6.5rem" }} />
          <input placeholder="Notes" value={form.notes} onChange={set("notes")} />
          <button type="submit">Add line</button>
          {error && <span className="error">{error}</span>}
        </form>
      )}
    </div>
  );
}
