from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def setup_job(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id)
    return headers, job


def test_register_list_open_delete(client, db, tmp_path):
    headers, job = setup_job(client, db)
    pdf = tmp_path / "Lot 42 Layout.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")

    resp = client.post(
        f"/jobs/{job['id']}/documents", headers=headers,
        json={"file_path": str(pdf), "doc_type": "layout"},
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["filename"] == "Lot 42 Layout.pdf"
    assert doc["doc_type"] == "layout"

    docs = client.get(f"/jobs/{job['id']}/documents", headers=headers).json()
    assert len(docs) == 1

    resp = client.get(f"/documents/{doc['id']}/file", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "inline" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")

    assert client.delete(f"/documents/{doc['id']}", headers=headers).status_code == 204
    assert pdf.exists()  # delete only unregisters; the file is untouched
    assert client.get(f"/jobs/{job['id']}/documents", headers=headers).json() == []


def test_register_missing_file_404(client, db):
    headers, job = setup_job(client, db)
    resp = client.post(
        f"/jobs/{job['id']}/documents", headers=headers,
        json={"file_path": "C:/nope/missing.pdf"},
    )
    assert resp.status_code == 404


def test_field_role_can_read_not_write(client, db, tmp_path):
    headers, job = setup_job(client, db)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client.post(f"/jobs/{job['id']}/documents", headers=headers, json={"file_path": str(pdf)})

    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    docs = client.get(f"/jobs/{job['id']}/documents", headers=field).json()
    assert len(docs) == 1
    assert client.get(f"/documents/{docs[0]['id']}/file", headers=field).status_code == 200
    assert (
        client.post(f"/jobs/{job['id']}/documents", headers=field, json={"file_path": str(pdf)}).status_code
        == 403
    )
