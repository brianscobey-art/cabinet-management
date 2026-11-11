from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_compile_and_mark_field_measure_notes_sent(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    a = make_job(client, headers, account_id, community_id, job_code="FMN-0001", plan="Plan 1840 A")
    b = make_job(client, headers, account_id, community_id, job_code="FMN-0002", address="2 B St", lot_number="2")
    ids = [client.post(f"/jobs/{j['id']}/field-measure/notes", headers=headers, json={"body": body}).json()["id"]
           for j, body in ((a, "Range wall 2in short"), (a, "Window moved"), (b, "Sink wall off 1/2in"))]

    rows = client.get("/reports/field-measure-notes", headers=headers).json()
    assert {r["id"] for r in rows} == set(ids)
    first = next(r for r in rows if r["id"] == ids[0])
    assert first["job_code"] == "FMN-0001" and first["plan"] == "Plan 1840 A" and first["sent_at"] is None

    sent = client.post("/field-measure-notes/mark-sent", headers=headers,
                       json={"ids": ids[:2], "to": "alex.talley@carterlumber.com"})
    assert sent.status_code == 200, sent.text
    assert all(n["sent_to"] == "alex.talley@carterlumber.com" and n["sent_by"] for n in sent.json())

    assert [r["id"] for r in client.get("/reports/field-measure-notes", headers=headers).json()] == [ids[2]]
    every = client.get("/reports/field-measure-notes?include_sent=true", headers=headers).json()
    assert len(every) == 3

    # sent by mistake -> back on the list
    client.post("/field-measure-notes/mark-sent", headers=headers, json={"ids": [ids[1]], "sent": False})
    assert {r["id"] for r in client.get("/reports/field-measure-notes", headers=headers).json()} == {ids[1], ids[2]}
    assert client.post("/field-measure-notes/mark-sent", headers=headers, json={"ids": [99999]}).status_code == 404
