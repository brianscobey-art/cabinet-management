"""Jobs tab KSR filter (Brian 11/20/26): a job counts for its own KSR, else its
account's default; "none" shows the jobs nobody is credited for."""

from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def test_jobs_filter_and_show_ksr(client, db):
    make_user(db, email="admin@example.com", role=Role.admin)
    h = login(client, "admin@example.com")
    paula_acct, c1 = setup_account(client, h, name="Smith Homes", community="Oak Hill")
    bare_acct, c2 = setup_account(client, h, name="Jones Builders", community="Pine Run")
    assert client.patch(f"/accounts/{paula_acct}", headers=h, json={"ksr": "Paula Cook"}).status_code == 200

    from_account = make_job(client, h, paula_acct, c1, address="1 Oak Hill")
    overridden = make_job(client, h, paula_acct, c1, address="2 Oak Hill")
    assert client.patch(f"/jobs/{overridden['id']}", headers=h, json={"ksr": "Alex Talley"}).status_code == 200
    nobody = make_job(client, h, bare_acct, c2, address="3 Pine Run")

    rows = {j["id"]: j for j in client.get("/jobs", headers=h).json()}
    assert rows[from_account["id"]]["ksr"] == "Paula Cook"
    assert rows[overridden["id"]]["ksr"] == "Alex Talley"
    assert rows[nobody["id"]]["ksr"] is None

    ids = lambda **p: {j["id"] for j in client.get("/jobs", headers=h, params=p).json()}  # noqa: E731
    assert ids(ksr="Paula Cook") == {from_account["id"]}
    assert ids(ksr="paula") == {from_account["id"]}          # any spelling of the name
    assert ids(ksr="Alex Talley") == {overridden["id"]}
    assert ids(ksr="none") == {nobody["id"]}
