"""Push a sold job into CabinetTron (the Carter Kitchen and Bath app).

Server-side REST client against CabinetTron's API (default http://127.0.0.1:8000):
login -> find/create account + community -> create job -> room selections ->
quote named "CKB Pricing Import" with every line item. Credentials live in this
app's settings table (set them on the Settings page once).
"""

import httpx
from sqlalchemy.orm import Session

from app.sterling_app.compute import get_setting
from app.sterling_app.models import Job

TIMEOUT = 30.0


class ExportError(Exception):
    pass


def _client(db: Session) -> tuple[httpx.Client, str]:
    import os

    base = get_setting(
        db, "cabinettron_url", os.environ.get("CABINETTRON_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    email = get_setting(db, "cabinettron_email", "")
    password = get_setting(db, "cabinettron_password", "")
    if not email or not password:
        raise ExportError("CabinetTron login not configured — set it on the Settings page")
    client = httpx.Client(base_url=base, timeout=TIMEOUT)
    try:
        resp = client.post("/auth/token", data={"username": email, "password": password})
    except httpx.ConnectError:
        client.close()
        raise ExportError(f"CabinetTron is not reachable at {base} — is the server running?")
    if resp.status_code != 200:
        client.close()
        raise ExportError(f"CabinetTron login failed ({resp.status_code}) — check email/password")
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client, base


def _ok(resp: httpx.Response, doing: str) -> dict:
    if resp.status_code not in (200, 201):
        raise ExportError(f"CabinetTron rejected {doing} ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def _find_or_create_account(client: httpx.Client, name: str, job_type: str) -> dict:
    accounts = _ok(client.get("/accounts"), "account list")
    for acct in accounts:
        if acct["name"].strip().lower() == name.strip().lower():
            return acct
    acct_type = "retail" if job_type == "remodel" else "builder"
    return _ok(
        client.post("/accounts", json={"name": name, "type": acct_type}), "account create"
    )


def _find_or_create_community(client: httpx.Client, account_id: int, name: str) -> dict:
    detail = _ok(client.get(f"/accounts/{account_id}"), "account detail")
    for comm in detail.get("communities", []):
        if comm["name"].strip().lower() == name.strip().lower():
            return comm
    return _ok(
        client.post("/communities", json={"account_id": account_id, "name": name}),
        "community create",
    )


def export_job(db: Session, job: Job) -> dict:
    """Returns {"job_id": ..., "url": ...} of the created CabinetTron job."""
    if job.exported_job_id:
        raise ExportError(f"Already exported as CabinetTron job #{job.exported_job_id}")
    account_name = (job.builder or "").strip() or job.name.strip()

    client, base = _client(db)
    try:
        account = _find_or_create_account(client, account_name, job.job_type.value)
        community_id = None
        if job.community:
            community_id = _find_or_create_community(client, account["id"], job.community)["id"]

        payload = {
            "account_id": account["id"],
            "community_id": community_id,
            "lot_number": job.lot_number,
            "address": job.address or job.name,
            "job_type": job.job_type.value,
            "plan": job.plan,
            "sales_contact_name": job.sales_contact_name or "Brian Scobey",
            "sales_contact_phone": job.sales_contact_phone,
            "sales_contact_email": job.sales_contact_email or None,
            "field_contact_name": job.field_contact_name or job.sales_contact_name or "Brian Scobey",
            "field_contact_phone": job.field_contact_phone,
            "field_contact_email": job.field_contact_email or None,
            "notes": f"Imported from CKB Pricing Platform (pricing job #{job.id})."
            + (f"\n{job.notes}" if job.notes else ""),
        }
        ct_job = _ok(client.post("/jobs", json=payload), "job create")
        ct_job_id = ct_job["id"]

        for room in job.rooms:
            _ok(
                client.post(
                    f"/jobs/{ct_job_id}/rooms",
                    json={
                        "room": room.name,
                        "zone": room.zone,
                        "cabinet_brand": room.cabinet_brand,
                        "series": room.series,
                        "door_style": room.door_style,
                        "finish": room.finish,
                        "wood_species": room.wood_species,
                        "notes": room.notes,
                    },
                ),
                f"room selection '{room.name}'",
            )

        quote = _ok(
            client.post(
                f"/jobs/{ct_job_id}/quotes",
                json={"name": "CKB Pricing Import", "notes": "Priced in the CKB Pricing Platform."},
            ),
            "quote create",
        )
        for room in job.rooms:
            room_label = f"{room.name} {room.zone}".strip() if room.zone else room.name
            for line in room.lines:
                _ok(
                    client.post(
                        f"/quotes/{quote['id']}/lines",
                        json={
                            "room": room_label[:100],
                            "qty": line.qty,
                            "sku": line.sku,
                            "color": room.finish,
                            "list_price": str(line.list_price),
                            "notes": line.description or line.notes,
                        },
                    ),
                    f"quote line {line.sku}",
                )
        return {"job_id": ct_job_id, "url": f"{base}/jobs/{ct_job_id}"}
    finally:
        client.close()
