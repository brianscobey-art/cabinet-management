"""Spoken phase updates for the Phases page (Alex Talley's ask, 11/25/26).

Alex drives a community and says what he sees: "lot 12 drywall hung, lot 14
framing complete, lots 20 through 23 slab poured, lot 9 same". The phone's
speech recognition turns that into text; parse() turns the text into one
item per lot -- which house, which phase -- for a confirm list. Nothing is
saved here; the page saves what the user confirms.

Rules
  * A lot is "lot|lots|unit|units|house" + a number ("12", "12A", "twelve");
    lists ("12, 13 and 14") and ranges ("20 through 23", "20 to 23") work.
    No keyword at all is allowed too ("12 drywall hung").
  * The words after the lots up to the next lot are the phase: matched
    against PHASE_WORDS (longest phrase wins) or "phase 6" / "phase 4.1".
    "same" / "no change" / "still" re-confirms the house's current phase.
  * A lot number that isn't a lot in the community falls back to the house
    number of the address (Alex may read the mailbox).
"""
from __future__ import annotations

import re

from app.phases import PHASE_CODES, PHASE_LABELS

SAME = "same"

# Spoken words -> phase code. Longest phrase is tried first, so "framing
# complete" (4) beats "framing" (3) and "drywall hung" (6) beats "drywall".
PHASE_WORDS: dict[str, str] = {
    "dirt": "0", "staked": "0", "stake": "0", "not started": "0", "dirt staked": "0",
    "slab formed": "1", "formed": "1", "forms": "1", "form": "1",
    "slab poured": "2", "poured": "2", "slab": "2", "pour": "2",
    "framing start": "3", "framing started": "3", "framing": "3", "start framing": "3",
    "framing complete": "4", "framing done": "4", "framed": "4", "framing finished": "4",
    "ready to measure": "4", "measure": "4", "ready for measure": "4",
    "pre walk": "4.1", "prewalk": "4.1", "pre-walk": "4.1", "pre walk complete": "4.1",
    "windows": "4.2", "windows installed": "4.2", "windows in": "4.2",
    "roof": "4.3", "roof complete": "4.3", "roofed": "4.3", "shingles": "4.3", "roof on": "4.3",
    "mechanicals": "4.4", "mechanical": "4.4", "mechanicals complete": "4.4", "rough in": "4.4",
    "rough-in": "4.4", "electrical": "4.4", "plumbing": "4.4",
    "insulation": "4.5", "insulated": "4.5", "insulation complete": "4.5",
    "drywall ready": "5", "ready for drywall": "5", "board ready": "5",
    "drywall hung": "6", "hung": "6", "drywall up": "6", "sheetrock": "6", "sheetrock hung": "6",
    "rocked": "6", "hanging": "6", "drywall hanging": "6",
    "tape and float": "7", "tape float": "7", "taped": "7", "tape": "7", "float": "7", "floated": "7",
    "mud": "7", "mudded": "7", "drywall tape": "7", "taped and floated": "7",
    "textured": "8", "texture": "8",
    "trim": "9", "trimmed": "9", "trim out": "9",
    "paint": "10", "painted": "10", "painting": "10",
    "cab delivered": "11", "cabinets delivered": "11", "delivered": "11", "cabinet delivered": "11",
    "cabinets installed": "12", "cabinet installed": "12", "installed": "12", "cabs installed": "12",
    "post walk": "13", "post walk complete": "13", "postwalk": "13",
    "punch": "14", "first punch": "14", "1st punch": "14", "punch complete": "14", "punched": "14",
    "blue tape": "15", "blue taped": "15", "blue tape complete": "15",
    "closed": "16", "close": "16", "done": "16",
    "same": SAME, "no change": SAME, "still": SAME, "unchanged": SAME, "same phase": SAME,
    "nothing new": SAME, "same as before": SAME,
}
_PHRASES = sorted(PHASE_WORDS, key=len, reverse=True)

_UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
# speech recognizers hear these for "for/to/too" in numbers sometimes; only in a number context
_LOT = r"(?:lots?|units?|houses?|homes?|address|number)"


def _words_to_digits(text: str) -> str:
    """'lot twenty three' -> 'lot 23', 'phase four point one' -> 'phase 4.1',
    'one hundred twelve' -> '112'."""
    toks = text.split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _TENS or t in _UNITS or t == "hundred":
            val, j = 0, i
            cur = 0
            while j < len(toks) and (toks[j] in _TENS or toks[j] in _UNITS or toks[j] == "hundred"):
                w = toks[j]
                if w == "hundred":
                    cur = (cur or 1) * 100
                elif w in _TENS:
                    cur += _TENS[w]
                else:
                    cur += _UNITS[w]
                j += 1
            val = cur
            out.append(str(val))
            i = j
            continue
        out.append(t)
        i += 1
    s = " ".join(out)
    return re.sub(r"\b(\d+) point (\d)\b", r"\1.\2", s)


def normalize(text: str) -> str:
    s = (text or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s.\-#]", " ", s)       # commas, periods at ends, etc.
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # keep decimal points only
    s = re.sub(r"#", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _words_to_digits(s)


def lot_key(v: str | None) -> str:
    """'012' -> '12', '12a' -> '12A'."""
    s = re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()
    m = re.match(r"^0*(\d+)([A-Z]*)$", s)
    return f"{int(m.group(1))}{m.group(2)}" if m else s


def _phase_of(words: str) -> tuple[str | None, str]:
    """Phase code (or SAME) for the words after a lot, plus what was heard."""
    w = f" {words.strip()} "
    m = re.search(r"\bphase (\d+(?:\.\d)?)\b", w)
    if m and m.group(1) in PHASE_CODES:
        return m.group(1), words.strip()
    for p in _PHRASES:
        if f" {p} " in w:
            return PHASE_WORDS[p], words.strip()
    return None, words.strip()


_NUM = r"\d+[a-z]?"


def _expand(lots_text: str) -> list[str]:
    """'12, 13 and 14' / '20 through 23' -> ['12','13','14'] / ['20'..'23']."""
    toks = re.findall(rf"{_NUM}|through|thru|to|-", lots_text)
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if (i + 2 < len(toks) and toks[i + 1] in ("through", "thru", "to", "-")
                and t.isdigit() and toks[i + 2].isdigit()):
            a, b = int(t), int(toks[i + 2])
            if a <= b and b - a <= 40:
                out.extend(str(n) for n in range(a, b + 1))
                i += 3
                continue
        if re.fullmatch(_NUM, t):
            out.append(t)
        i += 1
    return out


# One chunk = lots then words. A chunk starts at a lot keyword, or at a bare
# number that comes after the previous chunk's phase words.
_CHUNK = re.compile(
    rf"(?:{_LOT}\s+)?(?P<lots>{_NUM}(?:\s*(?:,|and|through|thru|to|-)?\s*{_NUM})*)\s+(?P<words>.*?)"
    rf"(?=\s+(?:{_LOT}\s+)?{_NUM}\s+(?!(?:through|thru|to)\b)[a-z]|\s+{_LOT}\s+{_NUM}|$)"
)


def split_commands(text: str) -> list[tuple[list[str], str]]:
    """Normalized text -> [(lots, phase words)]."""
    s = normalize(text)
    # "phase 6" must not read as lot 6: protect it before chunking
    s = re.sub(r"\bphase (\d+(?:\.\d)?)", lambda m: "phase_" + m.group(1).replace(".", "_"), s)
    out = []
    for m in _CHUNK.finditer(s):
        words = re.sub(r"phase_(\d+)_?(\d)?", lambda x: "phase " + x.group(1) + ("." + x.group(2) if x.group(2) else ""),
                       m.group("words"))
        words = re.sub(rf"^\s*(?:is|at|in|are|was|to|now|at phase)\s+", "", words)
        out.append((_expand(m.group("lots")), words))
    return out


def parse(text: str, rows: list[dict]) -> dict:
    """rows: the community's board rows ({job_id, job_code, lot_number,
    address, phase}). Returns {items, heard}: one item per lot mentioned --
    ok items have job_id + phase; others say what went wrong."""
    by_lot: dict[str, list[dict]] = {}
    by_street: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("lot_number"):
            by_lot.setdefault(lot_key(r["lot_number"]), []).append(r)
        m = re.match(r"^\s*(\d+)", r.get("address") or "")
        if m:
            by_street.setdefault(str(int(m.group(1))), []).append(r)

    items = []
    seen: dict[int, int] = {}
    for lots, words in split_commands(text):
        code, heard = _phase_of(words)
        for lot in lots:
            item = {"lot": lot.upper(), "heard": heard, "job_id": None, "job_code": None, "address": None,
                    "current_phase": None, "current_label": None, "phase": None, "phase_label": None,
                    "ok": False, "problem": None}
            hits = by_lot.get(lot_key(lot)) or by_street.get(lot_key(lot)) or []
            if len(hits) != 1:
                item["problem"] = ("no lot or house number " + lot.upper() + " in this community" if not hits
                                   else f"{len(hits)} houses match {lot.upper()}")
                items.append(item)
                continue
            r = hits[0]
            item.update(job_id=r["job_id"], job_code=r.get("job_code"), address=r.get("address"),
                        current_phase=r.get("phase"), current_label=PHASE_LABELS.get(r.get("phase") or ""))
            if code is None:
                item["problem"] = f'no phase heard in "{heard}"' if heard else "no phase heard"
            elif code == SAME:
                if not r.get("phase"):
                    item["problem"] = "said same, but the house has no phase yet"
                else:
                    item.update(phase=r["phase"], phase_label=PHASE_LABELS[r["phase"]], ok=True, same=True)
            else:
                item.update(phase=code, phase_label=PHASE_LABELS[code], ok=True)
            # the same house twice: the later one wins, the earlier is dropped
            if item["ok"] and item["job_id"] in seen:
                items[seen[item["job_id"]]]["ok"] = False
                items[seen[item["job_id"]]]["problem"] = "said again later -- the later one is used"
            if item["ok"]:
                seen[item["job_id"]] = len(items)
            items.append(item)
    return {"heard": normalize(text), "items": items}
