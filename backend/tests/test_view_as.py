from app.models import Role
from tests.conftest import login, make_user


def _setup(client, db):
    admin = make_user(db, email="admin@example.com", role=Role.admin)
    sales = make_user(db, email="sales@example.com", role=Role.sales)
    field = make_user(db, email="field@example.com", role=Role.field)
    return admin, sales, field, login(client, "admin@example.com")


def test_admin_views_as_another_user(client, db):
    admin, sales, field, headers = _setup(client, db)
    me = client.get("/auth/me", headers={**headers, "X-View-As": str(field.id)}).json()
    assert me["email"] == "field@example.com" and me["role"] == "field"
    assert me["viewed_by"] == admin.full_name

    # role checks follow the viewed user: a field user can't list users
    r = client.get("/auth/users", headers={**headers, "X-View-As": str(field.id)})
    assert r.status_code == 403
    # ...but the picker still loads, keyed on the real admin
    opts = client.get("/auth/view-as", headers={**headers, "X-View-As": str(field.id)}).json()
    assert {o["id"] for o in opts} == {sales.id, field.id}

    # read-only: nothing saves under the other person's name
    r = client.post("/accounts", json={"name": "X", "type": "builder"},
                    headers={**headers, "X-View-As": str(sales.id)})
    assert r.status_code == 403 and "read-only" in r.json()["detail"]

    # no header -> yourself
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "admin@example.com" and me["viewed_by"] is None


def test_non_admin_header_is_ignored(client, db):
    admin, sales, field, _ = _setup(client, db)
    headers = login(client, "sales@example.com")
    me = client.get("/auth/me", headers={**headers, "X-View-As": str(admin.id)}).json()
    assert me["email"] == "sales@example.com" and me["viewed_by"] is None
    assert client.get("/auth/view-as", headers=headers).status_code == 403


def test_view_as_unknown_user(client, db):
    _, _, _, headers = _setup(client, db)
    assert client.get("/auth/me", headers={**headers, "X-View-As": "99999"}).status_code == 404
