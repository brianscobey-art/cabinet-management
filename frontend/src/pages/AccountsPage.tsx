import { FormEvent, useEffect, useState } from "react";
import {
  Account,
  AccountDetail,
  createAccount,
  createCommunity,
  getAccount,
  listAccounts,
  listKsrs,
  updateAccount,
} from "../api";

export default function AccountsPage({ canWrite }: { canWrite: boolean }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState<AccountDetail | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("builder");
  const [ksrs, setKsrs] = useState<string[]>([]);

  const refresh = () => listAccounts().then(setAccounts).catch((e) => setError(e.message));

  useEffect(() => {
    refresh();
    listKsrs().then(setKsrs).catch(() => {});
  }, []);

  async function setAccountKsr(id: number, ksr: string) {
    setError("");
    try {
      await updateAccount(id, { ksr: ksr || null });
      setAccounts((prev) => prev.map((a) => (a.id === id ? { ...a, ksr: ksr || null } : a)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set KSR");
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createAccount({ name, type });
      setName("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div>
      <div className="page-head">
        <h2>Accounts</h2>
      </div>
      {canWrite && (
        <form className="inline-form" onSubmit={submit}>
          <input placeholder="Account name *" value={name} onChange={(e) => setName(e.target.value)} required />
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="builder">builder</option>
            <option value="retail">retail</option>
          </select>
          <button type="submit">Add account</button>
        </form>
      )}
      {error && <p className="error">{error}</p>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>KSR (default for its jobs)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td>{a.type}</td>
                <td>
                  {canWrite ? (
                    <select
                      value={a.ksr ?? ""}
                      onChange={(e) => setAccountKsr(a.id, e.target.value)}
                      style={!a.ksr ? { color: "#b23" } : undefined}
                    >
                      <option value="">— unassigned —</option>
                      {ksrs.map((k) => (
                        <option key={k} value={k}>{k}</option>
                      ))}
                    </select>
                  ) : (
                    a.ksr ?? <span className="muted">unassigned</span>
                  )}
                </td>
                <td>
                  <button className="link-btn" onClick={() => getAccount(a.id).then(setSelected)}>
                    communities
                  </button>
                </td>
              </tr>
            ))}
            {accounts.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No accounts yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <CommunitiesCard
          account={selected}
          canWrite={canWrite}
          onChange={() => getAccount(selected.id).then(setSelected)}
        />
      )}
    </div>
  );
}

function CommunitiesCard({
  account,
  canWrite,
  onChange,
}: {
  account: AccountDetail;
  canWrite: boolean;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const [market, setMarket] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createCommunity({ account_id: account.id, name, market: market || undefined });
      setName("");
      setMarket("");
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="card">
      <h3>{account.name} — communities</h3>
      {account.communities.length === 0 ? (
        <p className="muted">None yet.</p>
      ) : (
        <ul>
          {account.communities.map((c) => (
            <li key={c.id}>
              {c.name}
              {c.market ? ` (${c.market})` : ""}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form className="inline-form" onSubmit={submit}>
          <input placeholder="Community name *" value={name} onChange={(e) => setName(e.target.value)} required />
          <input placeholder="Market" value={market} onChange={(e) => setMarket(e.target.value)} />
          <button type="submit">Add community</button>
          {error && <span className="error">{error}</span>}
        </form>
      )}
    </div>
  );
}
