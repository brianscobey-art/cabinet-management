from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def setup_job(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id)
    return headers, job


def test_room_zone_rows(client, db):
    """Kitchen perimeter and island are separate rows — the two-colors case."""
    headers, job = setup_job(client, db)

    perimeter = {
        "room": "Kitchen", "zone": "Perimeter", "cabinet_brand": "Everluxe",
        "series": "Craftsman", "door_style": "Shaker", "finish": "White", "wood_species": "Maple",
    }
    island = {**perimeter, "zone": "Island", "finish": "Navy"}
    bath = {"room": "Master Bath", "door_style": "Shaker", "finish": "Gray"}

    for payload in (perimeter, island, bath):
        assert client.post(f"/jobs/{job['id']}/rooms", headers=headers, json=payload).status_code == 201

    detail = client.get(f"/jobs/{job['id']}", headers=headers).json()
    rooms = detail["room_selections"]
    assert len(rooms) == 3
    kitchen = [r for r in rooms if r["room"] == "Kitchen"]
    assert {r["zone"] for r in kitchen} == {"Perimeter", "Island"}
    assert {r["finish"] for r in kitchen} == {"White", "Navy"}
    # the two-years-later question: what door style went in the master bath?
    master = next(r for r in rooms if r["room"] == "Master Bath")
    assert master["door_style"] == "Shaker"


def test_room_update_and_delete(client, db):
    headers, job = setup_job(client, db)
    room = client.post(
        f"/jobs/{job['id']}/rooms", headers=headers, json={"room": "Laundry", "finish": "White"}
    ).json()

    resp = client.patch(f"/rooms/{room['id']}", headers=headers, json={"finish": "Stone Gray"})
    assert resp.status_code == 200
    assert resp.json()["finish"] == "Stone Gray"

    assert client.delete(f"/rooms/{room['id']}", headers=headers).status_code == 204
    assert client.get(f"/jobs/{job['id']}/rooms", headers=headers).json() == []


def test_hardware_crud(client, db):
    headers, job = setup_job(client, db)
    resp = client.post(
        f"/jobs/{job['id']}/hardware", headers=headers,
        json={"room": "Kitchen", "vendor": "Top Knobs", "item": "Bar pull 5in matte black", "qty": 18},
    )
    assert resp.status_code == 201
    hw = resp.json()
    assert hw["qty"] == 18

    resp = client.patch(f"/hardware/{hw['id']}", headers=headers, json={"qty": 22})
    assert resp.json()["qty"] == 22

    assert client.delete(f"/hardware/{hw['id']}", headers=headers).status_code == 204


def test_selections_404_on_missing_job(client, db):
    headers, _ = setup_job(client, db)
    assert client.post("/jobs/9999/rooms", headers=headers, json={"room": "Kitchen"}).status_code == 404


def test_field_role_reads_but_cannot_write_selections(client, db):
    headers, job = setup_job(client, db)
    client.post(f"/jobs/{job['id']}/rooms", headers=headers, json={"room": "Kitchen"})

    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    assert client.get(f"/jobs/{job['id']}/rooms", headers=field).status_code == 200
    assert client.post(f"/jobs/{job['id']}/rooms", headers=field, json={"room": "Bath"}).status_code == 403
