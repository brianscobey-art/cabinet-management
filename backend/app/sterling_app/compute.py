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
        effective_multiplier=mult,
        net_each=Decimal("0") if excluded else net_each(line.list_price, mult),
        cost=cost,
        excluded=excluded,
    )


def _room_list(room: Room) -> Decimal:
    """Extended Everluxe list (all lines, incl. appliance placeholders) — matches
    the 2020 quote's net total for verification."""
    return money(sum((Decimal(l.list_price) * l.qty for l in room.lines), Decimal("0")))


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
    skus = {line.sku.strip() for room in job.rooms for line in room.lines}
    if not skus:
        return 0
    items = {
        i.sku: i
        for i in db.query(CatalogItem)
        .filter(CatalogItem.vendor == "Everluxe", CatalogItem.sku.in_(skus))
        .all()
    }
    total = 0
    for room in job.rooms:
        for line in room.lines:
            item = items.get(line.sku.strip())
            if item:
                total += (item.doors + item.drawers) * line.qty
    return total


def sku_unit_counts(db: Session, job: Job) -> tuple[int | None, int | None]:
    """(assembly boxes, install units) summed from per-SKU catalog values
    (Everluxe Install-Hardware file: value = boxes). None when no line item
    has per-SKU data — callers then fall back to the plan template."""
    skus = {line.sku.strip().upper() for room in job.rooms for line in room.lines}
    if not skus:
        return None, None
    items = {
        i.sku.upper(): i
        for i in db.query(CatalogItem).filter(CatalogItem.vendor == "Everluxe").all()
        if i.sku.upper() in skus
    }
    boxes = install = 0
    found = False
    for room in job.rooms:
        for line in room.lines:
            item = items.get(line.sku.strip().upper())
            if item and (item.assemble_value is not None or item.install_value is not None):
                found = True
                boxes += (item.assemble_value or 0) * line.qty
                install += (item.install_value or 0) * line.qty
    return (boxes, install) if found else (None, None)


def tops_total(db: Session, tops) -> dict:
    """Top Pricing Sheet math: per-area sqft (rounded to whole) x rate + sinks
    + cutouts. Rate is already the charge rate — tops add to sale after margin."""
    rate = Decimal(tops.rate_sqft) if tops.rate_sqft is not None else matrix_rate(db, "top_rate")
    k_sink = matrix_rate(db, "top_k_sink")
    v_sink = matrix_rate(db, "top_v_sink")
    cutout = matrix_rate(db, "top_cutout")
    sqft = {"Kitchen": Decimal("0"), "Vanity": Decimal("0")}
    for p in tops.pieces:
        area = "Vanity" if p.area == "Vanity" else "Kitchen"
        sqft[area] += Decimal(p.qty) * Decimal(p.width) * Decimal(p.depth) / Decimal("144")
    k_sqft = sqft["Kitchen"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    v_sqft = sqft["Vanity"].quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    kitchen = money(k_sqft * rate + tops.k_sinks * (k_sink + cutout))
    vanity = money(v_sqft * rate + tops.v_sinks * (v_sink + cutout))
    return {
        "rate": rate, "k_sqft": k_sqft, "v_sqft": v_sqft,
        "kitchen": kitchen, "vanity": vanity, "total": money(kitchen + vanity),
    }


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


def job_totals(db: Session, job: Job) -> dict:
    """All computed money on a job.

    simple model: cabinets + hardware + install.
    matrix model (DRH Pricing Sheet): cabinets + freight(% of cab) + hardware
    material + sales tax(7% materials) + assembly($10/box) + install
    + hardware labor + delivery = COGS; sell = round(COGS / (1 - margin)).
    """
    fallback = job_multiplier(db, job)
    room_costs = {room.id: _room_cost(room, fallback) for room in job.rooms}
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
    if job.install_mode != InstallMode.none:
        if job.install_price is not None:
            install_cost = money(job.install_price)
        elif install_units:
            install_cost = money(Decimal(install_units) * install_rate)
        elif rates:
            install_cost = money(rates.cabinet_install)
        if job.install_mode in (InstallMode.with_knobs, InstallMode.with_handles):
            hardware_labor = money(hw_qty * hardware_rate)

    # PIA: flat add-on to install (difficult jobs), applied on top of whatever
    # the install computed to — even a flat install price.
    pia = money(job.pia_amount) if job.pia_amount else Decimal("0.00")
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
    tops = tops_total(db, tops_rec)["total"] if tops_rec else Decimal("0.00")
    cab_sell = sell
    sell = money(sell + tops)

    # Allocate sell across rooms by share of TOTAL cost; the remainder is the
    # install+hardware portion so rooms + install/hw always foot to the job sell.
    allocated: dict[int, Decimal] = {room.id: Decimal("0.00") for room in job.rooms}
    if cost > 0:
        running = Decimal("0")
        for room in job.rooms:
            share = money(
                (cab_sell * room_costs[room.id] / cost).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            allocated[room.id] = share
            running += share
        install_hw_sell = money(cab_sell - running)
    else:
        install_hw_sell = Decimal("0.00")

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
        "cost": cost,
        "tops": tops,
        "sell": sell,
        "allocated": allocated,
        "install_hw_sell": install_hw_sell,
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
    )
