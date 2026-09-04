"""Pricing rollups: line -> room -> job, with sell allocated per room.

Sell is computed at the job level (margin mode or fixed plan price) and
allocated back to rooms proportionally by cost, so a printed per-room quote
always foots to the job total.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.sterling_app.models import (
    CatalogItem,
    CostModel,
    DoorStyle,
    InstallMode,
    Job,
    LineItem,
    PlanInstall,
    PricingMode,
    Room,
    Setting,
)
from app.sterling_app.pricing import (
    DEFAULT_MARGIN_PCT,
    DEFAULT_MULTIPLIER,
    MATRIX_DEFAULTS,
    is_excluded,
    line_cost,
    money,
    net_each,
    sell_from_margin,
)
from app.sterling_app.schemas import JobDetail, JobListItem, LineOut, RoomOut


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def default_multiplier(db: Session) -> Decimal:
    return Decimal(get_setting(db, "default_multiplier", str(DEFAULT_MULTIPLIER)))


def default_margin_pct(db: Session) -> Decimal:
    return Decimal(get_setting(db, "default_margin_pct", str(DEFAULT_MARGIN_PCT)))


def matrix_rate(db: Session, key: str) -> Decimal:
    return Decimal(get_setting(db, key, MATRIX_DEFAULTS[key]))


def hardware_kind(sku: str | None) -> str | None:
    """3910* = knob, 156* = handle — the letters after are just the color."""
    s = (sku or "").strip().upper()
    if s.startswith("3910"):
        return "knob"
    if s.startswith("156"):
        return "handle"
    return None


NATIONAL_MARKERS = ("drh", "dr horton", "century")


def is_national(builder: str | None) -> bool:
    """DRH + Century get the national tier (0.21 / 10%); everyone else retail."""
    text = (builder or "").lower()
    return any(m in text for m in NATIONAL_MARKERS)


def job_multiplier(db: Session, job: Job) -> Decimal:
    """Per-quote Everluxe multiplier: job override, else the settings default."""
    if job.multiplier_override is not None:
        return Decimal(job.multiplier_override)
    return default_multiplier(db)


def line_out(line: LineItem, fallback_multiplier: Decimal) -> LineOut:
    mult = line.multiplier if line.multiplier is not None else fallback_multiplier
    excluded = is_excluded(line.sku)
    cost = Decimal("0") if excluded else line_cost(line.list_price, line.qty, mult)
    return LineOut(
        id=line.id,
        room_id=line.room_id,
        sku=line.sku,
        description=line.description,
        qty=line.qty,
        list_price=line.list_price,
        multiplier=line.multiplier,
        notes=line.notes,
        for_room_id=line.for_room_id,
        effective_multiplier=mult,
        net_each=Decimal("0") if excluded else net_each(line.list_price, mult),
        cost=cost,
        excluded=excluded,
    )


def _room_list(room: Room) -> Decimal:
    """Extended Everluxe list (all lines, incl. appliance placeholders) — matches
    the 2020 quote's net total for verification."""
    return money(sum((Decimal(l.list_price) * l.qty for l in room.lines), Decimal("0")))


def catalog_by_sku(db: Session, vendor: str | None = "Everluxe") -> dict:
    """Catalog keyed by SKU *and* by its un-handed base, so a layout's B18L
    finds the B18 the catalog actually carries. The exact SKU always wins."""
    from app.sterling_app.layout_parse import base_sku

    q = db.query(CatalogItem)
    if vendor:
        q = q.filter(CatalogItem.vendor == vendor)
    items = q.all()
    out: dict[str, CatalogItem] = {}
    for item in items:                      # bases first, exact SKUs overwrite
        base = base_sku(item.sku.upper())
        if base != item.sku.upper():
            out.setdefault(base, item)
    for item in items:
        out[item.sku.upper()] = item
    return out


def catalog_lookup(catalog: dict, sku: str):
    """Exact SKU, else the same cabinet without its L/R handing."""
    from app.sterling_app.layout_parse import base_sku

    key = sku.strip().upper()
    return catalog.get(key) or catalog.get(base_sku(key))


def is_lumber_room(room: Room) -> bool:
    return room.name.strip().lower() == "lumber"


def _room_cost(room: Room, fallback_multiplier: Decimal) -> Decimal:
    return money(
        sum(
            (line_out(line, fallback_multiplier).cost for line in room.lines),
            Decimal("0"),
        )
    )


def resolve_price_group(db: Session, door_style: str | None) -> int | None:
    """Room door style/color -> Everluxe price group (1-5)."""
    if not door_style:
        return None
    style = db.query(DoorStyle).filter(DoorStyle.name.ilike(door_style.strip())).first()
    return style.price_group if style else None


def group_price(item: CatalogItem, group: int | None) -> Decimal:
    if group:
        price = getattr(item, f"price_g{group}", None)
        if price is not None:
            return price
    return item.list_price


def find_plan_install(db: Session, job: Job) -> PlanInstall | None:
    if not job.plan:
        return None
    matches = db.query(PlanInstall).filter(PlanInstall.plan.ilike(job.plan.strip())).all()
    if not matches:
        return None
    if len(matches) > 1 and job.builder:
        builder = job.builder.lower()
        for m in matches:
            # "DRH PC" / "DRH Montgomery" vs builder "DR Horton Panama City" — match loosely.
            tail = m.division.lower().replace("drh", "").strip()
            if tail and tail in builder:
                return m
    return matches[0]


def hardware_qty(db: Session, job: Job) -> int:
    """Knob/pull count = doors + drawers across all cabinet lines."""
    if job.hardware_qty_override is not None:
        return job.hardware_qty_override
    if not any(room.lines for room in job.rooms):
        return 0
    catalog = catalog_by_sku(db)
    total = 0
    for room in job.rooms:
        for line in room.lines:
            item = catalog_lookup(catalog, line.sku)
            if item:
                total += (item.doors + item.drawers) * line.qty
    return total


def sku_unit_counts(db: Session, job: Job) -> tuple[int | None, int | None]:
    """(assembly boxes, install units) summed from per-SKU catalog values
    (Everluxe Install-Hardware file: value = boxes). None when no line item
    has per-SKU data — callers then fall back to the plan template."""
    if not any(room.lines for room in job.rooms):
        return None, None
    catalog = catalog_by_sku(db)
    boxes = install = 0
    found = False
    for room in job.rooms:
        for line in room.lines:
            item = catalog_lookup(catalog, line.sku)
            if item and (item.assemble_value is not None or item.install_value is not None):
                found = True
                boxes += (item.assemble_value or 0) * line.qty
                install += (item.install_value or 0) * line.qty
    return (boxes, install) if found else (None, None)


def tops_total(db: Session, tops) -> dict:
    """Top Pricing Sheet math: per-area sqft (rounded to whole) x rate + sinks
    + cutouts. Rate is already the charge rate — tops add to sale after margin."""
    def per_plan(attr, key):
        """The plan's own rate when it has one, else the global setting."""
        val = getattr(tops, attr, None)
        return Decimal(val) if val is not None else matrix_rate(db, key)

    rate = Decimal(tops.rate_sqft) if tops.rate_sqft is not None else matrix_rate(db, "top_rate")
    k_sink = per_plan("k_sink_rate", "top_k_sink")
    v_sink = per_plan("v_sink_rate", "top_v_sink")
    k_cutout = per_plan("k_cutout_rate", "top_cutout")
    v_cutout = per_plan("v_cutout_rate", "top_cutout")
    k_cuts = getattr(tops, "k_cutouts", None)
    v_cuts = getattr(tops, "v_cutouts", None)
    k_cuts = tops.k_sinks if k_cuts is None else k_cuts
    v_cuts = tops.v_sinks if v_cuts is None else v_cuts
    sqft = {"Kitchen": Decimal("0"), "Vanity": Decimal("0")}
    for p in tops.pieces:
        area = "Vanity" if p.area == "Vanity" else "Kitchen"
        sqft[area] += Decimal(p.qty) * Decimal(p.width) * Decimal(p.depth) / Decimal("144")
    k_sqft = sqft["Kitchen"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    v_sqft = sqft["Vanity"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    kitchen = money(k_sqft * rate + tops.k_sinks * k_sink + k_cuts * k_cutout)
    vanity = money(v_sqft * rate + tops.v_sinks * v_sink + v_cuts * v_cutout)
    return {
        "rate": rate, "k_sqft": k_sqft, "v_sqft": v_sqft,
        "kitchen": kitchen, "vanity": vanity, "total": money(kitchen + vanity),
    }


VANITY_WORDS = ("vanity", "bath", "powder")


def tops_area_class(area: str | None) -> str:
    """Which rate table a top belongs to. Anything bath-ish prices as a vanity."""
    a = (area or "").strip().lower()
    return "Vanity" if any(w in a for w in VANITY_WORDS) else "Kitchen"


def tops_by_room(db: Session, tops) -> list[dict]:
    """Job tops, one row per room the pieces were measured in.

    Sqft rounds per room — that is the point of measuring by room — so a job
    with two kitchen-class rooms can land a dollar or two off the old single
    Kitchen rounding. Sinks and cutouts are counted for the whole job and ride
    on the first room of their rate class.
    """
    if not tops:
        return []
    rate = Decimal(tops.rate_sqft) if tops.rate_sqft is not None else matrix_rate(db, "top_rate")

    def per_plan(attr, key):
        val = getattr(tops, attr, None)
        return Decimal(val) if val is not None else matrix_rate(db, key)

    k_cuts = tops.k_sinks if tops.k_cutouts is None else tops.k_cutouts
    v_cuts = tops.v_sinks if tops.v_cutouts is None else tops.v_cutouts
    extras = {
        "Kitchen": money(tops.k_sinks * per_plan("k_sink_rate", "top_k_sink")
                         + k_cuts * per_plan("k_cutout_rate", "top_cutout")),
        "Vanity": money(tops.v_sinks * per_plan("v_sink_rate", "top_v_sink")
                        + v_cuts * per_plan("v_cutout_rate", "top_cutout")),
    }
    sink_counts = {"Kitchen": tops.k_sinks + k_cuts, "Vanity": tops.v_sinks + v_cuts}

    order: list[str] = []
    sqft: dict[str, Decimal] = {}
    for piece in tops.pieces:
        area = (piece.area or "Kitchen").strip() or "Kitchen"
        if area not in sqft:
            sqft[area] = Decimal("0")
            order.append(area)
        sqft[area] += Decimal(piece.qty) * Decimal(piece.width) * Decimal(piece.depth) / Decimal("144")

    rows = []
    claimed: set[str] = set()
    for area in order:
        cls = tops_area_class(area)
        sf = sqft[area].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        extra = Decimal("0.00")
        extra_qty = 0
        if cls not in claimed:                 # sinks land on the first room of the class
            claimed.add(cls)
            extra, extra_qty = extras[cls], sink_counts[cls]
        rows.append({
            "room": area, "rate_class": cls, "sqft": sf, "rate": rate,
            "surface": money(sf * rate), "extras": extra, "extra_qty": extra_qty,
            "total": money(sf * rate + extra),
        })
    # A rate class with sinks but no measured piece still has to be charged.
    for cls in ("Kitchen", "Vanity"):
        if cls not in claimed and extras[cls]:
            rows.append({
                "room": cls, "rate_class": cls, "sqft": Decimal("0"), "rate": rate,
                "surface": Decimal("0.00"), "extras": extras[cls],
                "extra_qty": sink_counts[cls], "total": extras[cls],
            })
    return rows


def national_pricing_rows(db: Session, division: str | None, door_style: str | None) -> list[dict]:
    """The workbook's Pricing Sheet, computed live: every plan's COGS -> sale.

    Per plan: list (at the chosen door style's price group) x 0.21, freight 10%,
    knob hardware, 7% tax, assembly/install from per-SKU values (fallback plan
    units), sale = round(COGS / (1 - margin)); margin = plan override or the
    national default.
    """
    from app.sterling_app.models import PlanTemplateItem, PlanTops

    group = resolve_price_group(db, door_style)
    mult = matrix_rate(db, "drh_multiplier")
    freight_pct = matrix_rate(db, "freight_pct")
    tax_pct = matrix_rate(db, "tax_pct")
    assem_rate = matrix_rate(db, "assem_rate")
    install_rate = matrix_rate(db, "install_rate")
    knob_mat = matrix_rate(db, "knob_material")
    knob_labor = matrix_rate(db, "knob_labor")
    default_margin = matrix_rate(db, "national_margin")

    items_q = db.query(PlanTemplateItem)
    if division:
        items_q = items_q.filter(PlanTemplateItem.division == division)
    catalog = {
        i.sku.upper(): i
        for i in db.query(CatalogItem).filter(CatalogItem.vendor == "Everluxe").all()
    }
    installs = {
        (r.division, r.plan): r
        for r in db.query(PlanInstall).all()
    }
    tops_by_plan = {
        (t.division, t.plan): tops_total(db, t)
        for t in db.query(PlanTops).all()
    }

    plans: dict[tuple, dict] = {}
    for it in items_q.all():
        key = (it.division, it.plan)
        p = plans.setdefault(key, {
            "list": Decimal("0"), "hw_qty": 0,
            "sku_boxes": 0, "sku_install": 0, "sku_units_found": False,
        })
        cat = catalog.get(it.sku.strip().upper())
        if cat:
            p["list"] += group_price(cat, group) * it.qty
            p["hw_qty"] += (cat.doors + cat.drawers) * it.qty
            if cat.assemble_value is not None or cat.install_value is not None:
                p["sku_units_found"] = True
                p["sku_boxes"] += (cat.assemble_value or 0) * it.qty
                p["sku_install"] += (cat.install_value or 0) * it.qty

    rows = []
    for (div, plan), p in sorted(plans.items()):
        rec = installs.get((div, plan))
        boxes = p["sku_boxes"] if p["sku_units_found"] else (rec.assembly_units if rec else 0)
        units = p["sku_install"] if p["sku_units_found"] else (rec.install_units if rec else 0)
        cabinets = money(p["list"] * mult)
        freight = money(cabinets * freight_pct)
        hw_material = money(p["hw_qty"] * knob_mat)
        tax = money((cabinets + hw_material) * tax_pct)
        assembly = money(Decimal(boxes) * assem_rate)
        install = money(Decimal(units) * install_rate + p["hw_qty"] * knob_labor)
        cogs = money(cabinets + freight + hw_material + tax + assembly + install)
        override = rec.margin_pct if rec and rec.margin_pct is not None else None
        margin = Decimal(override) if override is not None else default_margin
        sale = (
            money(sell_from_margin(cogs, margin).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if cogs else Decimal("0.00")
        )
        tp = tops_by_plan.get((div, plan))
        tops = tp["total"] if tp else Decimal("0.00")
        rows.append({
            "tops_kitchen": tp["kitchen"] if tp else Decimal("0.00"),
            "tops_vanity": tp["vanity"] if tp else Decimal("0.00"),
            "division": div, "plan": plan,
            "list_total": money(p["list"]), "cabinets": cabinets, "freight": freight,
            "hardware_qty": p["hw_qty"], "hardware_material": hw_material,
            "tax": tax, "assembly": assembly, "install": install,
            "cogs": cogs, "margin_pct": margin, "margin_override": override,
            "sale": sale,
            # Tops are at charge rates already — added AFTER margin (Brian's rule)
            "tops": tops, "total": money(sale + tops),
        })
    return rows


def national_plan_detail(db: Session, division: str, plan: str,
                         door_style: str | None) -> dict:
    """One plan off the national price sheet, opened up: every SKU priced and
    each step of COGS -> sale spelled out. Same math as national_pricing_rows,
    so the detail always agrees with the row it was opened from."""
    from app.sterling_app.models import PlanTemplateItem, PlanTops

    group = resolve_price_group(db, door_style)
    rates = {
        "multiplier": matrix_rate(db, "drh_multiplier"),
        "freight_pct": matrix_rate(db, "freight_pct"),
        "tax_pct": matrix_rate(db, "tax_pct"),
        "assem_rate": matrix_rate(db, "assem_rate"),
        "install_rate": matrix_rate(db, "install_rate"),
        "knob_material": matrix_rate(db, "knob_material"),
        "knob_labor": matrix_rate(db, "knob_labor"),
        "default_margin": matrix_rate(db, "national_margin"),
    }
    items = (
        db.query(PlanTemplateItem)
        .filter(PlanTemplateItem.division == division, PlanTemplateItem.plan == plan)
        .order_by(PlanTemplateItem.id)
        .all()
    )
    if not items:
        raise ValueError("Plan not found")
    catalog = {
        i.sku.upper(): i
        for i in db.query(CatalogItem).filter(CatalogItem.vendor == "Everluxe").all()
    }
    lines = []
    list_total = Decimal("0")
    hw_qty = sku_boxes = sku_install = 0
    units_found = False
    for it in items:
        cat = catalog.get(it.sku.strip().upper())
        if cat is None:
            lines.append({
                "sku": it.sku.strip(), "qty": it.qty, "description": None, "in_catalog": False,
                "list_each": Decimal("0"), "ext_list": Decimal("0"), "dealer_ext": Decimal("0"),
                "assem_each": 0, "assem_units": 0, "install_each": 0, "install_units": 0,
                "hw_each": 0, "hw_pieces": 0,
            })
            continue
        each = group_price(cat, group)
        ext = each * it.qty
        hw_each = (cat.doors or 0) + (cat.drawers or 0)
        asm_each = cat.assemble_value or 0
        inst_each = cat.install_value or 0
        if cat.assemble_value is not None or cat.install_value is not None:
            units_found = True
        list_total += ext
        hw_qty += hw_each * it.qty
        sku_boxes += asm_each * it.qty
        sku_install += inst_each * it.qty
        lines.append({
            "sku": cat.sku, "qty": it.qty, "description": cat.description, "in_catalog": True,
            "list_each": money(each), "ext_list": money(ext),
            "dealer_ext": money(ext * rates["multiplier"]),
            "assem_each": asm_each, "assem_units": asm_each * it.qty,
            "install_each": inst_each, "install_units": inst_each * it.qty,
            "hw_each": hw_each, "hw_pieces": hw_each * it.qty,
        })

    rec = db.query(PlanInstall).filter(
        PlanInstall.division == division, PlanInstall.plan == plan).first()
    boxes = sku_boxes if units_found else (rec.assembly_units if rec else 0)
    units = sku_install if units_found else (rec.install_units if rec else 0)
    cabinets = money(list_total * rates["multiplier"])
    freight = money(cabinets * rates["freight_pct"])
    hw_material = money(hw_qty * rates["knob_material"])
    tax = money((cabinets + hw_material) * rates["tax_pct"])
    assembly = money(Decimal(boxes) * rates["assem_rate"])
    install_cabinet = money(Decimal(units) * rates["install_rate"])
    hw_labor = money(hw_qty * rates["knob_labor"])
    install = money(Decimal(units) * rates["install_rate"] + hw_qty * rates["knob_labor"])
    cogs = money(cabinets + freight + hw_material + tax + assembly + install)
    override = rec.margin_pct if rec and rec.margin_pct is not None else None
    margin = Decimal(override) if override is not None else rates["default_margin"]
    sale = (
        money(sell_from_margin(cogs, margin).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if cogs else Decimal("0.00")
    )
    tops_rec = db.query(PlanTops).filter(
        PlanTops.division == division, PlanTops.plan == plan).first()
    tp = tops_total(db, tops_rec) if tops_rec else None
    tops = tp["total"] if tp else Decimal("0.00")
    return {
        "division": division, "plan": plan, "door_style": door_style, "price_group": group,
        "units_source": "sku" if units_found else "plan",
        "rates": rates,
        "lines": lines,
        "totals": {
            "list_total": money(list_total), "cabinets": cabinets, "freight": freight,
            "hardware_qty": hw_qty, "hardware_material": hw_material, "tax": tax,
            "assembly_boxes": boxes, "assembly": assembly,
            "install_units": units, "install_cabinet": install_cabinet,
            "hardware_labor": hw_labor, "install": install,
            "cogs": cogs, "margin_pct": margin, "margin_override": override, "sale": sale,
            "tops": tops,
            "tops_kitchen": tp["kitchen"] if tp else Decimal("0.00"),
            "tops_vanity": tp["vanity"] if tp else Decimal("0.00"),
            "total": money(sale + tops),
        },
    }


def _room_components(db: Session, job: Job, fallback: Decimal) -> dict[int, dict]:
    """Raw per-room drivers before any job-level override is applied.

    Everything here is genuinely the room's own: its cabinet cost, the hardware
    its doors and drawers call for, its assembly and install boxes, the lumber
    bought for it and the PIA it earned. Job-level overrides are reconciled
    afterwards in job_totals, so the rooms always foot to the job.
    """
    items = catalog_by_sku(db)
    # Lumber is entered in its own room but bought FOR a room.
    lumber_for: dict[int | None, Decimal] = {}
    for room in job.rooms:
        if not is_lumber_room(room):
            continue
        for line in room.lines:
            key = line.for_room_id
            lumber_for[key] = lumber_for.get(key, Decimal("0")) + line_out(line, fallback).cost

    out: dict[int, dict] = {}
    for room in job.rooms:
        if is_lumber_room(room):
            continue
        hw = boxes = install_units = 0
        for line in room.lines:
            item = catalog_lookup(items, line.sku)
            if not item:
                continue
            hw += (item.doors + item.drawers) * line.qty
            boxes += (item.assemble_value or 0) * line.qty
            install_units += (item.install_value or 0) * line.qty
        out[room.id] = {
            "room": room,
            "list": _room_list(room),
            "cabinets": _room_cost(room, fallback),
            "lumber": money(lumber_for.get(room.id, Decimal("0"))),
            "hardware_qty": hw,
            "boxes": boxes,
            "install_units": install_units,
            "pia": money(room.pia_amount) if room.pia_amount else Decimal("0.00"),
        }
    return out


def _share(part: int | Decimal, whole: int | Decimal, amount: Decimal) -> Decimal:
    """A room's slice of a job-level number, by its share of the driver."""
    if not whole:
        return Decimal("0.00")
    return money(Decimal(amount) * Decimal(part) / Decimal(whole))


def job_totals(db: Session, job: Job) -> dict:
    """All computed money on a job.

    simple model: cabinets + hardware + install.
    matrix model (DRH Pricing Sheet): cabinets + freight(% of cab) + hardware
    material + sales tax(7% materials) + assembly($10/box) + install
    + hardware labor + delivery = COGS; sell = round(COGS / (1 - margin)).
    """
    fallback = job_multiplier(db, job)
    room_costs = {room.id: _room_cost(room, fallback) for room in job.rooms}
    parts = _room_components(db, job, fallback)
    # "Lumber" room(s) = Carter-supplied material: taxed like any material but
    # never gets Everluxe freight, and shows as its own section above Cabinets.
    lumber_cost = money(
        sum((room_costs[r.id] for r in job.rooms if r.name.strip().lower() == "lumber"), Decimal("0"))
    )
    cabinets_cost = money(sum(room_costs.values(), Decimal("0")) - lumber_cost)
    matrix = job.cost_model == CostModel.matrix
    handles = job.install_mode == InstallMode.with_handles

    # Hardware material: qty from doors+drawers; unit cost from the chosen SKU,
    # else (matrix) the standard KNB/HNDL rate.
    hw_qty = hardware_qty(db, job)
    hw_unit = Decimal("0")
    if job.hardware_sku:
        item = (
            db.query(CatalogItem)
            .filter(CatalogItem.sku.ilike(job.hardware_sku.strip()))
            .order_by(CatalogItem.id)
            .first()
        )
        if item:
            mult = item.multiplier if item.multiplier is not None else fallback
            hw_unit = net_each(item.list_price, mult)
    elif matrix and job.install_mode in (InstallMode.with_knobs, InstallMode.with_handles):
        hw_unit = matrix_rate(db, "handle_material" if handles else "knob_material")
    hardware_material = money(hw_unit * hw_qty)

    freight_pct = (
        Decimal(job.freight_pct_override)
        if job.freight_pct_override is not None
        else matrix_rate(db, "retail_freight_pct")  # default tier = retail 11.8%
    )
    freight = money(cabinets_cost * freight_pct) if matrix else Decimal("0.00")
    # 7% sales tax on materials applies on BOTH cost models — always in cost
    # before margin is applied. Lumber is material, so it's in the tax base.
    tax = money((cabinets_cost + lumber_cost + hardware_material) * matrix_rate(db, "tax_pct"))

    rates = find_plan_install(db, job)
    # Unit precedence: job override > per-SKU sums from the lines > plan template.
    sku_boxes, sku_install = sku_unit_counts(db, job)
    if job.assembly_boxes is not None:
        boxes = job.assembly_boxes
    elif sku_boxes is not None:
        boxes = sku_boxes
    else:
        boxes = rates.assembly_units if rates else 0
    assembly_rate = (
        Decimal(job.assembly_rate) if job.assembly_rate is not None else matrix_rate(db, "assem_rate")
    )
    # Labor (assembly, install, hardware) prices the same on both cost models;
    # only freight/tax/delivery are matrix-specific.
    assembly = money(Decimal(boxes) * assembly_rate)
    delivery = money(matrix_rate(db, "delivery")) if matrix else Decimal("0.00")

    # Install labor: flat override wins; else install units x per-box rate
    # (per-quote dropdown, default $25). Units = plan's, else the box count.
    install_rate = (
        Decimal(job.install_rate) if job.install_rate is not None else matrix_rate(db, "install_rate")
    )
    if sku_install is not None:
        install_units = sku_install
    elif rates and rates.install_units:
        install_units = rates.install_units
    else:
        install_units = boxes
    # Labor by hardware family when a SKU is chosen (3910=knob $1, 156=handle $2);
    # explicit per-quote rate still wins.
    kind = hardware_kind(job.hardware_sku)
    handles_eff = (kind == "handle") if kind else handles
    hardware_rate = (
        Decimal(job.hardware_rate)
        if job.hardware_rate is not None
        else matrix_rate(db, "handle_labor" if handles_eff else "knob_labor")
    )
    install_cost = Decimal("0.00")
    hardware_labor = Decimal("0.00")
    install_minimum = matrix_rate(db, "install_minimum")
    install_min_applied = False
    if job.install_mode != InstallMode.none:
        if job.install_price is not None:
            install_cost = money(job.install_price)
        elif install_units:
            install_cost = money(Decimal(install_units) * install_rate)
        elif rates:
            install_cost = money(rates.cabinet_install)
        if job.install_mode in (InstallMode.with_knobs, InstallMode.with_handles):
            hardware_labor = money(hw_qty * hardware_rate)
    install_raw = install_cost
    # No job installs for less than the minimum — unless a flat price was set
    # or the job was marked exempt. Only once there are cabinets to install.
    if (job.install_mode != InstallMode.none and job.install_price is None
            and not job.install_min_override and cabinets_cost > 0
            and install_cost < install_minimum):
        install_cost = money(install_minimum)
        install_min_applied = True

    # PIA: flat add-on to install (difficult jobs), applied on top of whatever
    # the install computed to — even a flat install price.
    # PIA is entered on the room that earned it; the old job-level field still
    # counts for quotes priced before rooms carried their own.
    room_pia = money(sum((p["pia"] for p in parts.values()), Decimal("0")))
    pia = money((money(job.pia_amount) if job.pia_amount else Decimal("0.00")) + room_pia)
    # Reported install = cabinet install + hardware install labor + PIA
    # (matches the workbook's "Install w/ Knobs / Handles" convention).
    install_cost = money(install_cost + hardware_labor + pia)

    hardware_cost = money(hardware_material + hardware_labor)
    cost = money(
        lumber_cost + cabinets_cost + freight + hardware_material + tax
        + assembly + install_cost + delivery
    )

    if job.pricing_mode == PricingMode.plan and job.plan_price is not None:
        sell = money(job.plan_price)
    else:
        margin = job.margin_pct if job.margin_pct is not None else default_margin_pct(db)
        sell = sell_from_margin(cost, margin) if cost else Decimal("0.00")
        sell = money(sell.quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # whole-dollar sale prices

    # Countertops (Top Pricing form): rate is already the charge rate — added
    # AFTER margin. Rooms allocate over the cabinet sell only.
    from app.sterling_app.models import PlanTops

    tops_rec = db.query(PlanTops).filter(PlanTops.job_id == job.id).first()
    # On a job the tops price by room, so the total is the sum of the room rows.
    # (Plan/national tops keep tops_total's single Kitchen/Vanity rounding.)
    tops_rows = tops_by_room(db, tops_rec) if tops_rec else []
    tops = money(sum((r["total"] for r in tops_rows), Decimal("0")))
    cab_sell = sell
    sell = money(sell + tops)

    # Break the job's money back down per room. Each room carries its own
    # cabinets, lumber, hardware, tax, labor and PIA; anything a room cannot own
    # (delivery, unassigned lumber, a flat install override, job-level PIA) lands
    # in the job-level bucket so the rows always foot to the job total.
    tot_hw = sum(p["hardware_qty"] for p in parts.values())
    tot_boxes = sum(p["boxes"] for p in parts.values())
    tot_units = sum(p["install_units"] for p in parts.values())
    tot_cab = money(sum((p["cabinets"] for p in parts.values()), Decimal("0")))
    materials_total = money(cabinets_cost + lumber_cost + hardware_material)
    base_install = money(install_cost - hardware_labor - pia)

    breakdown: list[dict] = []
    for room in job.rooms:
        p = parts.get(room.id)
        if p is None:
            continue
        r_hw_mat = _share(p["hardware_qty"], tot_hw, hardware_material)
        r_freight = _share(p["cabinets"], tot_cab, freight)
        r_materials = money(p["cabinets"] + p["lumber"] + r_hw_mat)
        r_tax = _share(r_materials, materials_total, tax)
        r_assembly = _share(p["boxes"], tot_boxes, assembly)
        r_install = money(
            _share(p["install_units"], tot_units, base_install)
            + _share(p["hardware_qty"], tot_hw, hardware_labor)
            + p["pia"]
        )
        r_cost = money(
            p["cabinets"] + p["lumber"] + r_freight + r_hw_mat + r_tax + r_assembly + r_install
        )
        breakdown.append({
            "room_id": room.id, "name": room.name, "zone": room.zone,
            "line_count": len(room.lines),
            "list": p["list"], "cabinets": p["cabinets"], "lumber": p["lumber"],
            "hardware_qty": p["hardware_qty"], "hardware_material": r_hw_mat,
            "freight": r_freight, "tax": r_tax,
            "boxes": p["boxes"], "assembly": r_assembly,
            "install_units": p["install_units"], "install": r_install, "pia": p["pia"],
            "cost": r_cost,
        })

    rooms_cost = money(sum((b["cost"] for b in breakdown), Decimal("0")))
    job_level_cost = money(cost - rooms_cost)

    # Sell follows cost share, whole dollars, remainder to the job-level bucket.
    allocated: dict[int, Decimal] = {room.id: Decimal("0.00") for room in job.rooms}
    running = Decimal("0")
    if cost > 0:
        for b in breakdown:
            share = money(
                (cab_sell * b["cost"] / cost).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            b["sell"] = share
            b["margin_amount"] = money(share - b["cost"])
            b["margin_pct"] = money(b["margin_amount"] / share * 100) if share else None
            allocated[b["room_id"]] = share
            running += share
    else:
        for b in breakdown:
            b["sell"] = Decimal("0.00")
            b["margin_amount"] = Decimal("0.00")
            b["margin_pct"] = None
    install_hw_sell = money(cab_sell - running)

    return {
        "list_total": money(sum((_room_list(r) for r in job.rooms), Decimal("0"))),
        "lumber_cost": lumber_cost,
        "cabinets_cost": cabinets_cost,
        "hardware_qty": hw_qty,
        "hardware_unit_cost": hw_unit,
        "hardware_material": hardware_material,
        "hardware_labor": hardware_labor,
        "hardware_cost": hardware_cost,
        "freight": freight,
        "freight_pct_effective": freight_pct,
        "tax": tax,
        "assembly": assembly,
        "assembly_boxes_effective": boxes,
        "multiplier_effective": fallback,
        "install_rate_effective": install_rate,
        "hardware_rate_effective": hardware_rate,
        "assembly_rate_effective": assembly_rate,
        "pia": pia,
        "install_units_effective": install_units,
        "delivery": delivery,
        "install_cost": install_cost,
        "install_raw": install_raw,
        "install_minimum": install_minimum,
        "install_min_applied": install_min_applied,
        "cost": cost,
        "tops": tops,
        "sell": sell,
        "allocated": allocated,
        "install_hw_sell": install_hw_sell,
        "rooms_breakdown": breakdown,
        "tops_rows": tops_rows,
        "job_level_cost": job_level_cost,
        "job_level_sell": install_hw_sell,
        "job_pia": money(job.pia_amount) if job.pia_amount else Decimal("0.00"),
        "cab_sell": cab_sell,
    }


def room_out(db: Session, room: Room, sell: Decimal | None = None) -> RoomOut:
    fallback = job_multiplier(db, room.job)
    return RoomOut(
        id=room.id,
        job_id=room.job_id,
        name=room.name,
        zone=room.zone,
        cabinet_brand=room.cabinet_brand,
        series=room.series,
        door_style=room.door_style,
        finish=room.finish,
        wood_species=room.wood_species,
        notes=room.notes,
        pia_amount=room.pia_amount,
        lines=[line_out(line, fallback) for line in room.lines],
        list_total=_room_list(room),
        cost=_room_cost(room, fallback),
        sell=sell if sell is not None else Decimal("0.00"),
    )


def _margins(cost: Decimal, sell: Decimal) -> tuple[Decimal, Decimal | None]:
    margin_amount = money(sell - cost)
    margin_pct = money(margin_amount / sell * 100) if sell else None
    return margin_amount, margin_pct


def job_list_item(db: Session, job: Job) -> JobListItem:
    t = job_totals(db, job)
    cost, sell = t["cost"], t["sell"]
    margin_amount, margin_pct = _margins(cost, sell)
    return JobListItem(
        id=job.id,
        name=job.name,
        builder=job.builder,
        community=job.community,
        lot_number=job.lot_number,
        plan=job.plan,
        ksr=job.ksr,
        job_type=job.job_type,
        stage=job.stage,
        room_count=len(job.rooms),
        cost=cost,
        sell=sell,
        margin_amount=margin_amount,
        margin_pct_actual=margin_pct,
        exported_job_id=job.exported_job_id,
        updated_at=job.updated_at,
        last_activity=max(job.updated_at, job.last_opened_at) if job.last_opened_at else job.updated_at,
    )


def job_detail(db: Session, job: Job) -> JobDetail:
    t = job_totals(db, job)
    cost, sell, allocated = t["cost"], t["sell"], t["allocated"]
    margin_amount, margin_pct = _margins(cost, sell)
    return JobDetail(
        id=job.id,
        name=job.name,
        builder=job.builder,
        community=job.community,
        lot_number=job.lot_number,
        address=job.address,
        plan=job.plan,
        job_type=job.job_type,
        stage=job.stage,
        pricing_mode=job.pricing_mode,
        margin_pct=job.margin_pct,
        plan_price=job.plan_price,
        multiplier_override=job.multiplier_override,
        freight_pct_override=job.freight_pct_override,
        assembly_boxes=job.assembly_boxes,
        multiplier_effective=t["multiplier_effective"],
        freight_pct_effective=t["freight_pct_effective"],
        assembly_boxes_effective=t["assembly_boxes_effective"],
        install_rate=job.install_rate,
        install_rate_effective=t["install_rate_effective"],
        hardware_rate=job.hardware_rate,
        hardware_rate_effective=t["hardware_rate_effective"],
        assembly_rate=job.assembly_rate,
        assembly_rate_effective=t["assembly_rate_effective"],
        pia_amount=job.pia_amount,
        pia=t["pia"],
        ksr=job.ksr,
        install_units_effective=t["install_units_effective"],
        sales_contact_name=job.sales_contact_name,
        sales_contact_phone=job.sales_contact_phone,
        sales_contact_email=job.sales_contact_email,
        field_contact_name=job.field_contact_name,
        field_contact_phone=job.field_contact_phone,
        field_contact_email=job.field_contact_email,
        notes=job.notes,
        cost_model=job.cost_model,
        install_mode=job.install_mode,
        install_price=job.install_price,
        install_min_override=job.install_min_override or 0,
        install_min_applied=t["install_min_applied"],
        install_minimum=t["install_minimum"],
        install_raw=t["install_raw"],
        hardware_sku=job.hardware_sku,
        hardware_qty_override=job.hardware_qty_override,
        exported_job_id=job.exported_job_id,
        exported_at=job.exported_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        rooms=sorted(
            (room_out(db, room, allocated.get(room.id)) for room in job.rooms),
            key=lambda r: (r.name.strip().lower() != "lumber", r.id),  # Lumber first
        ),
        list_total=t["list_total"],
        lumber_cost=t["lumber_cost"],
        cost=cost,
        sell=sell,
        margin_amount=margin_amount,
        margin_pct_actual=margin_pct,
        cabinets_cost=t["cabinets_cost"],
        hardware_qty=t["hardware_qty"],
        hardware_unit_cost=t["hardware_unit_cost"],
        hardware_material=t["hardware_material"],
        hardware_labor=t["hardware_labor"],
        hardware_cost=t["hardware_cost"],
        freight=t["freight"],
        tax=t["tax"],
        assembly=t["assembly"],
        delivery=t["delivery"],
        install_cost=t["install_cost"],
        install_hw_sell=t["install_hw_sell"],
        tops=t["tops"],
        rooms_breakdown=t["rooms_breakdown"],
        tops_rows=t["tops_rows"],
        job_level_cost=t["job_level_cost"],
        job_level_sell=t["job_level_sell"],
        job_pia=t["job_pia"],
    )
