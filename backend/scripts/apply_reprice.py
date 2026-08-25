"""Write the Reprice Proposal's levelled prices into contract_prices.

Turns a proposal into the thing the reprice check polices. Dry run by default.

    python -m scripts.apply_reprice --effective 2026-09-01 [--commit]

prior_price is only recorded when the plan's current PO is a FIXED price across
every house. Where the PO varies, the average is not a contract price, and
storing it would let the check report "the old price was used" about a number
nobody ever agreed to. Those rows get a null prior, so a mismatch is reported
as "check" instead of an accusation.
"""

import argparse
import statistics
from datetime import date
from decimal import Decimal


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--effective", required=True, help="YYYY-MM-DD")
    ap.add_argument("--source", default="Pricing leveling")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    eff = date.fromisoformat(args.effective)

    from app.sterling_app import reports
    from app.sterling_app.database import SessionLocal
    from app.sterling_app.models import ContractPrice

    with SessionLocal() as db:
        proposal = reports.run("reprice-proposal", db)
        margin = reports.run("plan-margin", db)
        spread = {r["plan"]: r["po_price"] for r in margin["rows"]}

        moving = [r for r in proposal["rows"] if abs(r["change"]) > 0.5]
        print(f"{len(moving)} plans change price, effective {eff}\n")
        print(f"  {'plan':<24}{'division':<16}{'now':>9}{'new':>9}{'prior kept':>12}")

        written = 0
        for r in moving:
            fixed = str(spread.get(r["plan"], "")).startswith("Fixed")
            prior = Decimal(str(r["current_po"])) if fixed else None
            print(f"  {r['plan'][:23]:<24}{r['division'][:15]:<16}"
                  f"{r['current_po']:>9,.0f}{r['new_price']:>9,.0f}"
                  f"{('yes' if fixed else 'no — PO varies'):>12}")

            row = (db.query(ContractPrice)
                   .filter(ContractPrice.division == r["division"],
                           ContractPrice.plan == r["plan"],
                           ContractPrice.effective_from == eff)
                   .first())
            if row is None:
                row = ContractPrice(division=r["division"], plan=r["plan"],
                                    effective_from=eff)
                db.add(row)
            row.price = Decimal(str(r["new_price"]))
            row.prior_price = prior
            row.color_upcharge = None
            row.source = args.source
            written += 1

        ups = [r for r in moving if r["change"] > 0]
        downs = [r for r in moving if r["change"] < 0]
        print(f"\n  {len(ups)} up (+${sum(r['impact'] for r in ups):,.0f}), "
              f"{len(downs)} down (${sum(r['impact'] for r in downs):,.0f}), "
              f"net ${sum(r['impact'] for r in moving):,.0f} over 12 months")
        no_prior = sum(1 for r in moving if not str(spread.get(r["plan"], "")).startswith("Fixed"))
        if no_prior:
            print(f"  {no_prior} plan(s) have a varying PO, so no prior price is recorded")

        if args.commit:
            db.commit()
            print(f"\ncommitted {written} contract prices effective {eff}")
        else:
            db.rollback()
            print(f"\ndry run — would write {written} (pass --commit)")


if __name__ == "__main__":
    main()
