"""Read a 2020 Design cabinet layout (the printed .pdf, or its text pasted in)
and turn it into a quote-ready SKU list.

Two things are on a layout and both count:

* the SKUs drawn on the plan — one label per cabinet, so the same SKU appearing
  three times means qty 3 (B33 B33 B33);
* the qty-prefixed callout blocks down the side — Accessories / Trim / Skins /
  Other — written "3-F630", "1-TUK", "8-SCR", "1-2x4-8".

A SKU can show up in both (FPV4296 gets drawn AND listed). The callout list is
the authority: a SKU that is called out is counted from the callout only, and
its drawn copies are disregarded. Fillers (F3xx / F6xx) and the dishwasher
return panel DWR3 count ONLY from the callout list — drawn anywhere else they
are ignored (and reported, so nothing vanishes silently).

Appliance placeholders never get priced or ordered (the standing rule). Short
fillers (F630, F330, F636...) are cut from 42" stock, so they come through as
the 42" filler of the same width (F630 -> F642, F330 -> F342) and merge with
any of that SKU already on the list; the conversions are reported alongside.
"""

from __future__ import annotations

import io
import re

# Never priced or ordered — they mark where the appliance goes.
APPLIANCE_PREFIXES = ("RANGE", "REF.", "REF2", "DISHW", "MICRO", "HOOD")

# Short fillers are cut from 42" stock of the same width: F630 -> F642, F330 -> F342.
CUT_STOCK_RE = re.compile(r"^F(\d)(30|36)$")


# Counted from the callout list only; a drawn copy anywhere else is disregarded.
# Older 2020 catalogs draw fillers as BF3 / VF6 / WF3 (base, vanity, wall filler);
# those are fillers too, so the drawn label never becomes a quote line.
CALLOUT_ONLY_RE = re.compile(r"^(F[36]\d{2}|[BVW]F\d{1,3}|DWR\d)$")

# Room tags drawn on a layout ("Ba1", "Ba2", "Bath 2") are not cabinets.
ROOM_TAG_RE = re.compile(r"^(?:[A-Z][a-z]+\s?#?\d{1,2}|BA\d)$")
# Panel pieces drawn on an island or peninsula (FBP3636, PBP72) are cut from the
# back panel sheet in the callout list, so with a BP9636 callout they are not
# extra lines.
PANEL_PIECE_RE = re.compile(r"^[FP]BP\d{2,4}$")

# Hardware: a callout ("33-Black Knobs", "26-3910-SN", "50-Knobs") is the piece
# count; a drawn or header label ("Hardware: 3910-SN") only names the style.
HARDWARE_SKU_RE = re.compile(r"^(3910|156)[A-Z0-9-]*$|^(STD)?-?(KNOB|PULL)S?(-[A-Z]+)?$")
HARDWARE_WORDS_RE = re.compile(r"(?i)\b(knobs?|pulls?|hardware|per color sheet)\b|^(3910|156)")

# 2020 Design catalog names -> the Everluxe catalog name Sterling quotes. Only
# applied when the drawn name is NOT already a catalog SKU, so a current layout
# is untouched. Each rule came out of the 15-layout check (11/5/26).
ALIAS_EXACT = {
    "S3/4": "SCR", "SCRIBE": "SCR", "SM8": "SCR",
    "SHOE": "SHM", "SHOE8": "SHM", "SHMO8": "SHM", "SM10": "SHM",
    "BTK8": "TKC", "TK8": "TKC", "TOEKICK": "TKC", "TOE": "TKC",
    "OCM8": "OCM", "90OCM": "OCM", "90DOCM": "OCM",
    "BEP3": "DWR3",
    "36X96BACKPANEL": "BP9636", "PANEL36X96": "BP9636",
    "OMC3396": "O339624", "REP2496": "REPV2496",
}
ALIAS_RE = [
    (re.compile(r"^VSB(\d\d)$"), r"VS\1"),                 # vanity sink base
    (re.compile(r"^V(\d\d)21$"), r"VS\1"),                 # V3021 = 30" vanity sink, 21 deep
    (re.compile(r"^(?:FD)?B0?9$"), r"BT9"),                 # no 9" base in Everluxe: it is the tray base
    (re.compile(r"^VDB(\d\d)(?:-3|\d{4})?$"), r"3VDB\1"),   # vanity drawer base
    (re.compile(r"^W(\d{4})-(\d\d)D?$"), r"W\1\2"),         # W3018-15 -> W301815
    (re.compile(r"^(?:RW|WR-)(\d{4})$"), r"W\g<1>24"),       # refrigerator wall, 24 deep
    (re.compile(r"^B(\d\d)-2$"), r"B\1"),                   # two-door base
    (re.compile(r"^LS(\d\d)(?:-?[LR])?$"), r"LSB\1"),        # lazy susan base
    (re.compile(r"^WDC?(\d{4})$"), r"DCW\1"),                # diagonal corner wall
    (re.compile(r"^BT0(\d)$"), r"BT\1"),                     # tray base BT09 -> BT9
    (re.compile(r"^U(\d{4})$"), r"U\g<1>24"),                # utility, 24 deep
]
# Crown by lineal feet: Everluxe stocks 8' crown (CM8); a 10' callout is
# re-counted to cover the same footage (3 x CM10 = 30' -> 4 x CM8).
CROWN_FEET = {"CM10": 10, "CROWN": 8, "CM2-1/2": 8, "CM2-1/2\"": 8}


def catalog_name(sku: str, known: set[str]) -> str:
    """Drawn/called-out name -> the catalog SKU it orders as."""
    if known and (sku in known or base_sku(sku) in known):
        return sku
    if sku in ALIAS_EXACT:
        return ALIAS_EXACT[sku]
    for pat, rep in ALIAS_RE:
        if pat.match(sku):
            return pat.sub(rep, sku)
    return sku


def filler_stock(sku: str) -> str:
    """The 42\" filler a short one is cut from — or the SKU unchanged."""
    m = CUT_STOCK_RE.match(sku)
    return f"F{m.group(1)}42" if m else sku

# "3-F630", "1-TUK", "59-Hardware", "1-2x4-8"
CALLOUT_RE = re.compile(r"^(\d{1,3})\s*-\s*([A-Za-z0-9][A-Za-z0-9./x-]*)$")

# Lumber callouts, by the name the tracker and the comparison summary use.
LUMBER = {
    "2X4-8": "2x4 (8')", "2X4X8": "2x4 (8')",
    "1X4-8": "1x4 (8')", "1X4X8": "1x4 (8')",
    "1X6-8": "1x6 (8')", "1X6X8": "1x6 (8')",
    "1/2PLY": '1/2" Plywood', "1/2-PLY": '1/2" Plywood', "PLY": '1/2" Plywood',
}

# A cabinet SKU has letters AND digits, no spaces: B33, 3VDB18, W302415, FPV4296.
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9./-]{1,19}$")


def base_sku(sku: str) -> str:
    """B18L -> B18. A trailing L/R after a digit is only the door swing, so it
    is dropped at intake and the line merges with its base SKU (Brian's rule)."""
    if len(sku) > 3 and sku[-1] in "LR" and sku[-2].isdigit():
        return sku[:-1]
    return sku


def _looks_like_sku(tok: str) -> bool:
    if not SKU_RE.match(tok) or '"' in tok:
        return False
    return any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)


def pdf_tokens(raw: bytes) -> list[str]:
    """Text runs off a layout PDF, one per drawn label.

    pypdf hands rotated labels back one character at a time, each new text
    object restarting at x=0 — so characters are glued back together until the
    x position resets, which is exactly where the next label starts.
    """
    from pypdf import PdfReader

    runs: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, font_dict, font_size):
        t = (text or "").strip()
        if t:
            runs.append((tm[4], tm[5], t))

    reader = PdfReader(io.BytesIO(raw))
    for page in reader.pages:
        page.extract_text(visitor_text=visit)
    return _glue_runs(runs)


def _glue_runs(runs: list[tuple[float, float, str]]) -> list[str]:
    """Runs -> labels. Two kinds of split get repaired:

    * rotated labels arrive one character at a time (glued until x resets);
    * a label or callout arrives in two pieces on the same line — "1" then
      "-F642", "7-WSV" then "42", "FPV" then "4296". A piece that starts with
      "-", or a run of digits right after a piece ending in a letter, belongs
      to the label before it when they share a baseline and read left to right.
    """
    placed: list[list] = []          # [x, y, text]
    buf, buf_x, buf_y, last_x = "", None, None, None
    for x, y, t in runs:
        if len(t) == 1 and not t.isspace():
            if last_x is not None and x <= last_x:  # new text object -> new label
                if buf:
                    placed.append([buf_x, buf_y, buf])
                buf = ""
            if not buf:
                buf_x, buf_y = x, y
            buf += t
            last_x = x
            continue
        if buf:
            placed.append([buf_x, buf_y, buf])
        buf, last_x = "", None
        placed.append([x, y, t])
    if buf:
        placed.append([buf_x, buf_y, buf])

    out: list[list] = []
    for x, y, t in placed:
        if out:
            px, py, pt = out[-1]
            # baselines wobble a few units between pieces; the wobble is small
            # next to the horizontal step between them
            same_line = x > px and abs(y - py) <= max(3.0, 0.25 * (x - px))
            continues = (t.startswith("-") and not pt.endswith("-")) or                         (t.isdigit() and pt[-1:].isalpha() and " " not in pt)
            if same_line and continues:
                out[-1][2] = pt + t
                continue
        out.append([x, y, t])
    return [t for _, _, t in out]


def _join_split_callouts(tokens: list[str]) -> list[str]:
    """Callouts the PDF hands back in pieces: "1-F63 6" -> "1-F636",
    "4-S" + "3/4" -> "4-S3/4", "1-90 OCM" / "1-36x96 Back Panel" -> one word."""
    out: list[str] = []
    for tok in tokens:
        if out and tok == "3/4" and re.fullmatch(r"\d{1,3}\s*-\s*S", out[-1]):
            out[-1] = out[-1] + "3/4"
            continue
        m = re.fullmatch(r"(\d{1,3})\s*-\s*(.+)", tok)
        if m and " " in m.group(2):
            word = re.sub(r"\s+", "", m.group(2)).upper()
            if (re.fullmatch(r"F\d{2}\d", word) or word in ALIAS_EXACT
                    or re.fullmatch(r"[A-Z0-9./-]{2,20}", word) and word.endswith(("OCM", "PANEL"))):
                tok = f"{m.group(1)}-{word}"
        out.append(tok)
    return out


def text_tokens(text: str) -> list[str]:
    """Tokens off pasted text — one per line, plus the words of a line that is a
    run of SKUs. A label line ("Plan: DRH4 Camden STD") is left whole, or "DRH4"
    would read as a cabinet.
    """
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line)
        # one callout with words after it ("1-36x96 Back Panel", "34-Black Knobs")
        # is read whole; its words alone would read as callouts of their own
        one_callout = re.match(r"\d{1,3}\s*-\s*\S", line) and not re.search(r"\s\d{1,3}\s*-", line)
        if ":" not in line and not one_callout:
            out.extend(p for p in line.split() if p != line)
    return out


def _known(sku: str, known: set[str]) -> bool:
    return (not known) or sku in known or base_sku(sku) in known


def parse_layout(*, raw: bytes | None = None, text: str | None = None,
                 known_skus: set[str] | None = None) -> dict:
    """Layout -> {plan, door_style, lines, cut_stock, lumber, ...}.

    known_skus (the Everluxe catalog) keeps stray drawing text out of the quote:
    anything that is not in the catalog only survives if it is shaped like a
    cabinet SKU, and it comes back flagged so nobody quotes a typo.
    """
    tokens = pdf_tokens(raw) if raw else text_tokens(text or "")
    known = {s.upper() for s in (known_skus or set())}

    # Read the header off the source, not the token stream — pasted text repeats
    # a line's words, which would let the match run past the value.
    source = text if (text and not raw) else " ".join(tokens)
    plan = door_style = None
    m = re.search(r"Plan:[ \t]*([^\n]{1,80}?)[ \t]*(?:Door Style:|Hardware:|\n|$)", source)
    if m:
        plan = m.group(1).strip()
    m = re.search(r"Door Style:[ \t]*([^\n]{1,60}?)[ \t]*(?:Hardware:|Accessories|\n|$)", source)
    if m:
        door_style = m.group(1).strip()

    drawn: dict[str, int] = {}
    called: dict[str, int] = {}
    lumber: dict[str, int] = {}
    hardware_pieces = 0
    excluded: dict[str, int] = {}
    cut_stock: dict[str, int] = {}

    hardware_style = None
    crown_feet = 0
    vendors = re.findall(r"Vendor:[ \t]*([^\n]{1,40}?)[ \t]*(?:Door Style:|Color:|\n|$)", source)
    tokens = _join_split_callouts([t.strip().strip(",;") for t in tokens])

    for tok in tokens:
        if not tok:
            continue

        # a hardware callout carries words ("33-Black Knobs", "37-Per Color Sheet")
        hw = re.match(r"^(\d{1,3})\s*-\s*(.+)$", tok)
        if hw and HARDWARE_WORDS_RE.search(hw.group(2)):
            hardware_pieces += int(hw.group(1))
            if HARDWARE_SKU_RE.match(hw.group(2).replace(" ", "").upper()):
                hardware_style = hw.group(2).upper()
            continue
        if " " in tok:
            if tok.upper().startswith("HARDWARE:"):
                hardware_style = tok.split(":", 1)[1].strip().upper() or hardware_style
            continue

        call = CALLOUT_RE.match(tok)
        if call:
            qty = int(call.group(1))
            sku = base_sku(catalog_name(call.group(2).upper(), known))
            if sku in CROWN_FEET:
                crown_feet += CROWN_FEET[sku] * qty
                continue
            if HARDWARE_SKU_RE.match(sku):
                hardware_pieces += qty
                hardware_style = sku
                continue
            if sku in LUMBER:
                lumber[LUMBER[sku]] = lumber.get(LUMBER[sku], 0) + qty
            elif sku == "HARDWARE":
                hardware_pieces += qty
            elif sku.startswith(APPLIANCE_PREFIXES):
                excluded[sku] = excluded.get(sku, 0) + qty
            else:
                stock = filler_stock(sku)
                if stock != sku:
                    cut_stock[sku] = cut_stock.get(sku, 0) + qty
                called[stock] = called.get(stock, 0) + qty
            continue

        if ROOM_TAG_RE.match(tok):
            continue
        sku = base_sku(tok.upper())
        if not _looks_like_sku(sku):
            continue
        if HARDWARE_SKU_RE.match(sku):      # "3910-SN" drawn = the style, not a count
            hardware_style = hardware_style or sku
            continue
        sku = base_sku(catalog_name(sku, known))
        if sku.startswith(APPLIANCE_PREFIXES):
            excluded[sku] = excluded.get(sku, 0) + 1
        else:
            # Kept even when the catalog has never heard of it — a real cabinet
            # must never vanish silently. It comes back flagged instead.
            # drawn fillers are never counted (callouts only), so no cut-stock
            # note for them — it would report a conversion that did not happen
            drawn[filler_stock(sku)] = drawn.get(filler_stock(sku), 0) + 1

    # The callout list is the authority: a called-out SKU is counted from the
    # callout only, and fillers / DWR3 are never counted from the drawing.
    lines = []
    ignored: list[dict] = []
    drawn_ignored: dict[str, int] = {}
    for sku, qty in drawn.items():
        stock = base_sku(sku)
        if sku in called or stock in called:
            key = sku if sku in called else stock
            drawn_ignored[key] = drawn_ignored.get(key, 0) + qty
            ignored.append({"sku": sku, "qty": qty, "why": "listed in the callouts — the callout count is used"})
            continue
        if CALLOUT_ONLY_RE.match(stock):
            ignored.append({"sku": sku, "qty": qty, "why": "counts only from the accessories list"})
            continue
        if PANEL_PIECE_RE.match(stock) and "BP9636" in called:
            ignored.append({"sku": sku, "qty": qty, "why": "cut from the back panel in the callouts"})
            continue
        lines.append({"sku": sku, "qty": qty, "notes": "drawn on the layout",
                      "in_catalog": _known(sku, known)})
    for sku, qty in called.items():
        dropped = drawn_ignored.get(sku, 0)
        note = "callout list" + (f" · {dropped} drawn, disregarded" if dropped else "")
        lines.append({"sku": sku, "qty": qty, "notes": note,
                      "in_catalog": _known(sku, known)})

    if crown_feet:
        called["CM8"] = called.get("CM8", 0) + -(-crown_feet // 8)
        lines.append({"sku": "CM8", "qty": -(-crown_feet // 8),
                      "notes": f"callout list · {crown_feet}' of crown as 8' sticks",
                      "in_catalog": _known("CM8", known)})
    warnings = []
    distinct_vendors = sorted({v.strip() for v in vendors if v.strip()})
    if len(distinct_vendors) > 1:
        warnings.append("This layout lists more than one vendor (" + ", ".join(distinct_vendors)
                        + "). Split the takeoff by vendor before ordering.")

    return {
        "plan": plan,
        "hardware_style": hardware_style,
        "vendors": distinct_vendors,
        "warnings": warnings,
        "door_style": door_style,
        "lines": lines,
        "cut_stock": [{"sku": s, "qty": q, "as": filler_stock(s)}
                      for s, q in sorted(cut_stock.items())],
        "excluded": [{"sku": s, "qty": q} for s, q in sorted(excluded.items())],
        "lumber": lumber,
        "hardware_pieces": hardware_pieces,
        "ignored": ignored,
        "unknown": sorted(l["sku"] for l in lines if not l["in_catalog"]),
        "token_count": len(tokens),
    }
