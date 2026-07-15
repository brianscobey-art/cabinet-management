from app.models import Role
from tests.conftest import login, make_user

CONTACTS = {
    "sales_contact_name": "Brian Scobey",
    "sales_contact_email": "brian@example.com",
    "field_contact_name": "Super Dave",
    "field_contact_phone": "850-555-0100",
}


def setup_account(client, headers, name="DR Horton", community="Sandy Ridge"):
    account_id = client.post("/accounts", headers=headers, json={"name": name, "type": "builder"}).json()["id"]
    community_id = client.post(
        "/communities", headers=headers, json={"account_id": account_id, "name": community}
    ).json()["id"]
    return account_id, community_id


def make_job(client, headers, account_id, community_id=None, **overrides):
    payload = {
        "account_id": account_id,
        "community_id": community_id,
        "lot_number": "42",
        "address": "123 Sandy Ridge Blvd",
        "job_type": "tract",
        **CONTACTS,
        **overrides,
    }
    resp = client.post("/jobs", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_get_job(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)

    job = make_job(client, headers, account_id, community_id)
    assert job["status"] == "quote"
    assert job["sales_contact_name"] == "Brian Scobey"

    resp = client.get(f"/jobs/{job['id']}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["account_name"] == "DR Horton"
    assert detail["community_name"] == "Sandy Ridge"
    assert detail["room_selections"] == []


def test_job_requires_contacts(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, _ = setup_account(client, headers)
    resp = client.post(
        "/jobs", headers=headers,
        json={"account_id": account_id, "address": "1 Main St", "job_type": "remodel"},
    )
    assert resp.status_code == 422  # both contacts are required at creation


def test_community_must_belong_to_account(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, _ = setup_account(client, headers)
    other_account, other_community = setup_account(client, headers, name="Century", community="Elsewhere")
    resp = client.post(
        "/jobs", headers=headers,
        json={
            "account_id": account_id, "community_id": other_community,
            "address": "1 Main St", "job_type": "tract", **CONTACTS,
        },
    )
    assert resp.status_code == 422


def test_list_jobs_filters(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    retail_id = client.post("/accounts", headers=headers, json={"name": "Smith Remodel", "type": "retail"}).json()["id"]

    make_job(client, headers, account_id, community_id)
    make_job(client, headers, retail_id, address="9 Oak Ln", lot_number=None, job_type="remodel")

    all_jobs = client.get("/jobs", headers=headers).json()
    assert len(all_jobs) == 2
    assert all_jobs[0]["account_name"]  # list items carry names

    by_account = client.get(f"/jobs?account_id={account_id}", headers=headers).json()
    assert len(by_account) == 1
    assert by_account[0]["community_name"] == "Sandy Ridge"

    by_search = client.get("/jobs?q=oak", headers=headers).json()
    assert len(by_search) == 1
    assert by_search[0]["address"] == "9 Oak Ln"


def test_closed_jobs_only_on_archive(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    make_job(client, headers, account_id, community_id, job_code="OPEN-1")
    done = make_job(client, headers, account_id, community_id, job_code="DONE-1", address="2 Done St", lot_number="2")
    client.patch(f"/jobs/{done['id']}", headers=headers, json={"status": "closed"})

    default = [j["job_code"] for j in client.get("/jobs", headers=headers).json()]
    assert default == ["OPEN-1"]  # closed hidden by default

    archive = [j["job_code"] for j in client.get("/jobs?archived=true", headers=headers).json()]
    assert archive == ["DONE-1"]  # archive shows only closed

    # explicit status filter can still reach closed if asked
    explicit = [j["job_code"] for j in client.get("/jobs?status_filter=closed", headers=headers).json()]
    assert explicit == ["DONE-1"]


def test_category_filter_national_vs_local(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    drh_id, drh_comm = setup_account(client, headers, name="DR Horton Montgomery", community="Halls Creek")
    local_id = client.post("/accounts", headers=headers, json={"name": "Jubilee Builders", "type": "builder"}).json()["id"]
    retail_id = client.post("/accounts", headers=headers, json={"name": "Jane Smith", "type": "retail"}).json()["id"]

    make_job(client, headers, drh_id, drh_comm, job_code="DR-1")
    make_job(client, headers, local_id, None, job_code="JB-1", address="2 Local Ln", lot_number=None)
    make_job(client, headers, retail_id, None, job_code="RET-1", address="3 Retail Rd", lot_number=None)

    national = [j["job_code"] for j in client.get("/jobs?category=national", headers=headers).json()]
    assert national == ["DR-1"]
    local = [j["job_code"] for j in client.get("/jobs?category=local", headers=headers).json()]
    assert sorted(local) == ["JB-1", "RET-1"]  # local builders AND retail


def test_jobs_sorted_by_job_code(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    make_job(client, headers, account_id, community_id, job_code="DRZZZ-0002", address="2 Z St")
    make_job(client, headers, account_id, community_id, job_code="DRAAA-0001", address="1 A St")
    make_job(client, headers, account_id, community_id, address="9 No Code Ln")  # no job_code

    codes = [j["job_code"] for j in client.get("/jobs", headers=headers).json()]
    assert codes == ["DRAAA-0001", "DRZZZ-0002", None]  # alphanumeric, uncoded last


def test_update_status_and_warranty_defaults(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, headers)
    job = make_job(client, headers, account_id, community_id)

    resp = client.patch(
        f"/jobs/{job['id']}", headers=headers,
        json={"status": "install", "install_date": "2026-08-15"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "install"
    # warranty_start defaults to install date per spec
    assert body["warranty_start_date"] == "2026-08-15"


def test_field_role_cannot_write_jobs(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    sales = login(client, "sales@example.com")
    account_id, community_id = setup_account(client, sales)
    job = make_job(client, sales, account_id, community_id)

    make_user(db, email="field@example.com", role=Role.field)
    field = login(client, "field@example.com")
    assert client.get(f"/jobs/{job['id']}", headers=field).status_code == 200
    assert client.patch(f"/jobs/{job['id']}", headers=field, json={"status": "ordered"}).status_code == 403
