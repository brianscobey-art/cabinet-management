from app.models import Role
from tests.conftest import login, make_user


def test_login_and_me(client, db):
    make_user(db, email="brian@example.com", role=Role.admin)
    headers = login(client, "brian@example.com")
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "brian@example.com"
    assert body["role"] == "admin"


def test_login_wrong_password(client, db):
    make_user(db, email="brian@example.com")
    resp = client.post("/auth/token", data={"username": "brian@example.com", "password": "nope-wrong"})
    assert resp.status_code == 401


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401


def test_admin_can_create_user(client, db):
    make_user(db, email="admin@example.com", role=Role.admin)
    headers = login(client, "admin@example.com")
    resp = client.post(
        "/auth/users",
        headers=headers,
        json={
            "email": "installer@example.com",
            "full_name": "Eddie Installer",
            "password": "password123",
            "role": "installer_coordinator",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "installer_coordinator"
    # new user can log in
    login(client, "installer@example.com")


def test_non_admin_cannot_create_user(client, db):
    make_user(db, email="sales@example.com", role=Role.sales)
    headers = login(client, "sales@example.com")
    resp = client.post(
        "/auth/users",
        headers=headers,
        json={
            "email": "x@example.com",
            "full_name": "X",
            "password": "password123",
            "role": "sales",
        },
    )
    assert resp.status_code == 403


def test_duplicate_email_rejected(client, db):
    make_user(db, email="admin@example.com", role=Role.admin)
    headers = login(client, "admin@example.com")
    payload = {
        "email": "dupe@example.com",
        "full_name": "Dupe",
        "password": "password123",
        "role": "field",
    }
    assert client.post("/auth/users", headers=headers, json=payload).status_code == 201
    assert client.post("/auth/users", headers=headers, json=payload).status_code == 409
