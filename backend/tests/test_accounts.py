from app.models import Role
from tests.conftest import login, make_user


def sales_headers(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    return login(client, "sales@example.com")


def test_account_and_community_crud(client, db):
    headers = sales_headers(client, db)

    resp = client.post("/accounts", headers=headers, json={"name": "DR Horton Pensacola", "type": "builder"})
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["id"]

    # duplicate name rejected
    resp = client.post("/accounts", headers=headers, json={"name": "DR Horton Pensacola", "type": "builder"})
    assert resp.status_code == 409

    resp = client.post(
        "/communities", headers=headers,
        json={"account_id": account_id, "name": "Sandy Ridge", "market": "Pensacola FL"},
    )
    assert resp.status_code == 201
    # duplicate community within account rejected
    resp = client.post("/communities", headers=headers, json={"account_id": account_id, "name": "Sandy Ridge"})
    assert resp.status_code == 409

    resp = client.get(f"/accounts/{account_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["type"] == "builder"
    assert [c["name"] for c in detail["communities"]] == ["Sandy Ridge"]


def test_account_rename(client, db):
    headers = sales_headers(client, db)
    account_id = client.post(
        "/accounts", headers=headers, json={"name": "Century", "type": "builder"}
    ).json()["id"]
    resp = client.patch(f"/accounts/{account_id}", headers=headers, json={"name": "Century Complete"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Century Complete"


def test_community_requires_existing_account(client, db):
    headers = sales_headers(client, db)
    resp = client.post("/communities", headers=headers, json={"account_id": 999, "name": "Nowhere"})
    assert resp.status_code == 404


def test_field_role_cannot_write_accounts(client, db):
    make_user(db, email="field@example.com", role=Role.field)
    headers = login(client, "field@example.com")
    resp = client.post("/accounts", headers=headers, json={"name": "X", "type": "retail"})
    assert resp.status_code == 403
    # but can read
    assert client.get("/accounts", headers=headers).status_code == 200
