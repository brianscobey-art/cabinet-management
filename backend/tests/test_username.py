from app.auth.router import derive_username
from app.models import Role
from tests.conftest import login, make_user


def test_derive_username():
    assert derive_username("Brian Scobey", "x@carterlumber.com") == "brian.scobey"
    assert derive_username("Mary Ann O'Neil", "x@carterlumber.com") == "mary.oneil"
    assert derive_username("Cher", "cher.only@carterlumber.com") == "cher.only"


def test_new_user_gets_first_last_and_can_sign_in_with_it(client, db):
    make_user(db, email="admin@example.com", role=Role.admin)
    headers = login(client, "admin@example.com")
    resp = client.post("/auth/users", headers=headers, json={
        "email": "alex.talley@carterlumber.com", "full_name": "Alex Talley",
        "role": "sales", "password": "secret-pass-1", "send_invite": False,
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["username"] == "alex.talley"
    # username signs in...
    assert client.post("/auth/token", data={"username": "alex.talley", "password": "secret-pass-1"}).status_code == 200
    # ...and so does the email, with the same password
    assert client.post("/auth/token", data={"username": "alex.talley@carterlumber.com", "password": "secret-pass-1"}).status_code == 200
    # a second Alex Talley gets a numbered name rather than a clash
    resp = client.post("/auth/users", headers=headers, json={
        "email": "alex.talley2@carterlumber.com", "full_name": "Alex Talley",
        "role": "sales", "password": "secret-pass-2", "send_invite": False,
    })
    assert resp.json()["user"]["username"] == "alex.talley2"
