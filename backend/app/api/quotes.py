from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, selectinload

from app.api.deps import read_access, write_access
from app.api.jobs import get_job_or_404
from app.database import get_db
from app.models import Quote, QuoteLineItem, QuoteStatus
from app.pricing import is_excluded, line_total, money, net_each

router = APIRouter(tags=["quotes"])


# --- Schemas ---

class QuoteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    notes: str | None = None


class LineCreate(BaseModel):
    room: str | None = Field(default=None, max_length=100)
    qty: int = Field(default=1, ge=1)
    sku: str = Field(min_length=1, max_length=100)
    product_code: str | None = Field(default=None, max_length=100)
    fin_end: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=100)
    list_price: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None


class LineUpdate(BaseModel):
    room: str | None = None
    qty: int | None = Field(default=None, ge=1)
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    product_code: str | None = None
    fin_end: str | None = None
    color: str | None = None
    list_price: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quote_id: int
    room: str | None
    qty: int
    sku: str
    product_code: str | None
    fin_end: str | None
    color: str | None
    list_price: Decimal
    notes: str | None
    # computed
    net_each: Decimal
    total: Decimal
    excluded: bool  # appliance placeholder — never sent to the supplier


class QuoteOut(BaseModel):
    id: int
    job_id: int
    name: str
    status: QuoteStatus
    multiplier: Decimal
    notes: str | None
    list_total: Decimal
    net_total: Decimal
    line_count: int


class QuoteDetail(QuoteOut):
    lines: list[LineOut]


def _line_out(line: QuoteLineItem, multiplier: Decimal) -> LineOut:
    return LineOut(
        id=line.id,
        quote_id=line.quote_id,
        room=line.room,
        qty=line.qty,
        sku=line.sku,
        product_code=line.product_code,
        fin_end=line.fin_end,
        color=line.color,
        list_price=line.list_price,
        notes=line.notes,
        net_each=net_each(line.list_price, multiplier),
        total=line_total(line.list_price, line.qty, multiplier),
        excluded=is_excluded(line.sku),
    )


def _quote_out(quote: Quote, cls=QuoteOut, **extra) -> QuoteOut:
    list_total = money(sum((line.list_price * line.qty for line in quote.lines), Decimal("0")))
    net_total = money(
        sum((line_total(line.list_price, line.qty, quote.multiplier) for line in quote.lines), Decimal("0"))
    )
    return cls(
        id=quote.id,
        job_id=quote.job_id,
        name=quote.name,
        status=quote.status,
        multiplier=quote.multiplier,
        notes=quote.notes,
        list_total=list_total,
        net_total=net_total,
        line_count=len(quote.lines),
        **extra,
    )


def get_quote_or_404(quote_id: int, db: Session) -> Quote:
    quote = (
        db.query(Quote)
        .options(selectinload(Quote.lines))
        .filter(Quote.id == quote_id)
        .first()
    )
    if quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
    return quote


# --- Routes ---

@router.get("/jobs/{job_id}/quotes", response_model=list[QuoteOut], dependencies=[Depends(read_access)])
def list_quotes(job_id: int, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    quotes = (
        db.query(Quote).options(selectinload(Quote.lines)).filter(Quote.job_id == job_id).order_by(Quote.id).all()
    )
    return [_quote_out(q) for q in quotes]


@router.post(
    "/jobs/{job_id}/quotes",
    response_model=QuoteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def create_quote(job_id: int, payload: QuoteCreate, db: Session = Depends(get_db)):
    get_job_or_404(job_id, db)
    quote = Quote(job_id=job_id, name=payload.name.strip(), notes=payload.notes)
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return _quote_out(quote)


@router.get("/quotes/{quote_id}", response_model=QuoteDetail, dependencies=[Depends(read_access)])
def get_quote(quote_id: int, db: Session = Depends(get_db)):
    quote = get_quote_or_404(quote_id, db)
    return _quote_out(quote, cls=QuoteDetail, lines=[_line_out(li, quote.multiplier) for li in quote.lines])


@router.post("/quotes/{quote_id}/accept", response_model=QuoteOut, dependencies=[Depends(write_access)])
def accept_quote(quote_id: int, db: Session = Depends(get_db)):
    quote = get_quote_or_404(quote_id, db)
    # Only one accepted quote per job — demote any other accepted scenario.
    db.query(Quote).filter(
        Quote.job_id == quote.job_id, Quote.id != quote.id, Quote.status == QuoteStatus.accepted
    ).update({Quote.status: QuoteStatus.draft})
    quote.status = QuoteStatus.accepted
    db.commit()
    db.refresh(quote)
    return _quote_out(quote)


@router.delete("/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(write_access)])
def delete_quote(quote_id: int, db: Session = Depends(get_db)):
    quote = get_quote_or_404(quote_id, db)
    if quote.status == QuoteStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot delete an accepted quote"
        )
    db.delete(quote)
    db.commit()


@router.post(
    "/quotes/{quote_id}/lines",
    response_model=LineOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_access)],
)
def add_line(quote_id: int, payload: LineCreate, db: Session = Depends(get_db)):
    quote = get_quote_or_404(quote_id, db)
    line = QuoteLineItem(quote_id=quote.id, **payload.model_dump())
    db.add(line)
    db.commit()
    db.refresh(line)
    return _line_out(line, quote.multiplier)


@router.patch("/quote-lines/{line_id}", response_model=LineOut, dependencies=[Depends(write_access)])
def update_line(line_id: int, payload: LineUpdate, db: Session = Depends(get_db)):
    line = db.get(QuoteLineItem, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(line, key, value)
    db.commit()
    db.refresh(line)
    return _line_out(line, line.quote.multiplier)


@router.delete(
    "/quote-lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(write_access)]
)
def delete_line(line_id: int, db: Session = Depends(get_db)):
    line = db.get(QuoteLineItem, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    db.delete(line)
    db.commit()
