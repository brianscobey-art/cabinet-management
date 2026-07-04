from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def setup_job(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id)
    return headers, job


def test_quote_lifecycle_and_totals(client, db):
    headers, job = setup_job(client, db)

    quote = client.post(f"/jobs/{job['id']}/quotes", headers=headers, json={"name": "Option A"}).json()
    assert quote["status"] == "draft"
    from decimal import Decimal

    assert Decimal(quote["multiplier"]) == Decimal("0.217")

    # B18 base cabinet: list 461.75 -> net each 100.20; qty 2 -> 200.40
    resp = client.post(
        f"/quotes/{quote['id']}/lines", headers=headers,
        json={"sku": "B18", "qty": 2, "list_price": "461.75", "room": "Kitchen"},
    )
    assert resp.status_code == 201, resp.text
    line = resp.json()
    assert line["net_each"] == "100.20"
    assert line["total"] == "200.40"
    assert line["excluded"] is False

    client.post(
        f"/quotes/{quote['id']}/lines", headers=headers,
        json={"sku": "W3030", "qty": 1, "list_price": "100.00"},
    )

    detail = client.get(f"/quotes/{quote['id']}", headers=headers).json()
    assert detail["line_count"] == 2
    assert detail["list_total"] == "1023.50"  # 461.75*2 + 100
    assert detail["net_total"] == "222.10"    # 200.40 + 21.70


def test_accept_demotes_other_quotes(client, db):
    headers, job = setup_job(client, db)
    a = client.post(f"/jobs/{job['id']}/quotes", headers=headers, json={"name": "Option A"}).json()
    b = client.post(f"/jobs/{job['id']}/quotes", headers=headers, json={"name": "Option B"}).json()

    assert client.post(f"/quotes/{a['id']}/accept", headers=headers).json()["status"] == "accepted"
    assert client.post(f"/quotes/{b['id']}/accept", headers=headers).json()["status"] == "accepted"

    quotes = {q["name"]: q["status"] for q in client.get(f"/jobs/{job['id']}/quotes", headers=headers).json()}
    assert quotes == {"Option A": "draft", "Option B": "accepted"}


def test_cannot_delete_accepted_quote(client, db):
    headers, job = setup_job(client, db)
    quote = client.post(f"/jobs/{job['id']}/quotes", headers=headers, json={"name": "Option A"}).json()
    client.post(f"/quotes/{quote['id']}/accept", headers=headers)
    assert client.delete(f"/quotes/{quote['id']}", headers=headers).status_code == 409


def test_excluded_sku_flagged_on_line(client, db):
    headers, job = setup_job(client, db)
    quote = client.post(f"/jobs/{job['id']}/quotes", headers=headers, json={"name": "Option A"}).json()
    line = client.post(
        f"/quotes/{quote['id']}/lines", headers=headers,
        json={"sku": "RANGE1.30", "qty": 1, "list_price": "0"},
    ).json()
    assert line["excluded"] is True


def test_field_role_cannot_write_quotes(client, db):
    headers, job = setup_job(client, db)
    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    assert client.post(f"/jobs/{job['id']}/quotes", headers=field, json={"name": "X"}).status_code == 403
    assert client.get(f"/jobs/{job['id']}/quotes", headers=field).status_code == 200
