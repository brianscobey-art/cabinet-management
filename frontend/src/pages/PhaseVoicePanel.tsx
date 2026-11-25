import { useEffect, useRef, useState } from "react";
import { VoiceItem, parseVoicePhases, setPhasesBulk } from "../api";

// Voice phase updates (Alex Talley 11/25/26): tap the mic, say "lot 12 drywall
// hung, lots 14 through 16 framing complete, lot 9 same", check the list,
// save. The text box takes typing or the phone keyboard's own dictation too,
// so it works where the browser has no speech recognition.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Rec = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SpeechRec: (new () => Rec) | undefined = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export default function PhaseVoicePanel({
  communityId,
  onSaved,
  onClose,
}: {
  communityId: number;
  onSaved: (saved: { job_id: number; phase: string; noted_at: string }[]) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [items, setItems] = useState<VoiceItem[] | null>(null);
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rec = useRef<Rec>(null);

  useEffect(() => () => rec.current?.stop(), []);

  function startMic() {
    if (!SpeechRec) return;
    setError("");
    const r = new SpeechRec();
    r.lang = "en-US";
    r.continuous = true;
    r.interimResults = true;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    r.onresult = (e: any) => {
      let finalText = "";
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else live += t;
      }
      if (finalText) setText((cur) => (cur ? `${cur.trim()}, ${finalText.trim()}` : finalText.trim()));
      setInterim(live);
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    r.onerror = (e: any) => {
      if (e.error !== "no-speech" && e.error !== "aborted") setError(`Microphone: ${e.error}`);
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
    };
    rec.current = r;
    r.start();
    setListening(true);
  }

  function stopMic() {
    rec.current?.stop();
    setListening(false);
  }

  async function check() {
    stopMic();
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const res = await parseVoicePhases(communityId, text);
      setItems(res.items);
      const c: Record<number, boolean> = {};
      res.items.forEach((it, i) => (c[i] = it.ok));
      setChecked(c);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!items) return;
    const pick = items.filter((it, i) => checked[i] && it.ok && it.job_id && it.phase);
    if (!pick.length) return;
    setBusy(true);
    try {
      const saved = await setPhasesBulk(
        pick.map((it) => ({ job_id: it.job_id!, phase: it.phase! })),
        "voice",
      );
      onSaved(saved);
      setText("");
      setItems(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const count = items ? items.filter((it, i) => checked[i] && it.ok).length : 0;

  return (
    <div className="card voice-panel">
      <div className="voice-head">
        <b>Voice update</b>
        <button className="link-btn" onClick={onClose}>
          close
        </button>
      </div>
      <p className="muted voice-hint">
        Say the lot and the phase: "lot 12 drywall hung, lots 14 through 16 framing complete, lot 9 same".
        "Same" keeps the phase and updates the date.
      </p>
      <div className="voice-input">
        {SpeechRec && (
          <button
            type="button"
            className={listening ? "mic-btn on" : "mic-btn"}
            onClick={listening ? stopMic : startMic}
            aria-label={listening ? "Stop listening" : "Start listening"}
          >
            {listening ? "■ Stop" : "🎤 Talk"}
          </button>
        )}
        <textarea
          rows={3}
          value={listening && interim ? `${text} ${interim}`.trim() : text}
          onChange={(e) => {
            setText(e.target.value);
            setItems(null);
          }}
          placeholder={SpeechRec ? "Tap Talk, or type / use the keyboard mic" : "Type, or use the keyboard's mic"}
        />
      </div>
      <div className="voice-actions">
        <button onClick={check} disabled={busy || !text.trim()}>
          {busy && !items ? "Checking…" : "Check"}
        </button>
        {text && (
          <button
            className="link-btn"
            onClick={() => {
              setText("");
              setItems(null);
            }}
          >
            clear
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}

      {items && (
        <>
          {items.length === 0 ? (
            <p className="muted">No lots heard. Start each one with "lot" and its number.</p>
          ) : (
            <div className="table-wrap">
              <table className="voice-table">
                <thead>
                  <tr>
                    <th />
                    <th>Lot</th>
                    <th>Now</th>
                    <th>New</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it, i) => (
                    <tr key={i} className={it.ok ? "" : "voice-bad"}>
                      <td>
                        <input
                          type="checkbox"
                          disabled={!it.ok}
                          checked={!!checked[i]}
                          onChange={() => setChecked((c) => ({ ...c, [i]: !c[i] }))}
                        />
                      </td>
                      <td>
                        {it.lot}
                        {it.address && <div className="muted voice-addr">{it.address}</div>}
                      </td>
                      <td>{it.current_label ?? "—"}</td>
                      <td>
                        {it.ok ? (
                          <>
                            {it.phase_label}
                            {it.same && <span className="muted"> (same)</span>}
                          </>
                        ) : (
                          <span className="voice-problem">{it.problem}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="voice-actions">
            <button onClick={save} disabled={busy || count === 0}>
              {busy ? "Saving…" : `Save ${count} lot${count === 1 ? "" : "s"}`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
