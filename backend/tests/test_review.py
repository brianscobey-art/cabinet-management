"""Submit for Review (Brian 11/17/26): the red button on a job puts a review on
the reviewer's My Stuff; the reviewer answers Approve or Hold for Review."""

from app.config import get_settings
from app.models import Role
from tests.conftest import login, make_user
from tests.test_jobs import make_job, setup_account


def _setup(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_review_emails", "boss@example.com")
    make_user(db, email="boss@example.com", role=Role.admin)
    make_user(db, email="sales@example.com", role=Role.sales)
    sales = login(client, "sales@example.com")
    boss = login(client, "boss@example.com")
    account_id, community_id = setup_account(client, sales)
    job = make_job(client, sales, account_id, community_id)
    return sales, boss, job


def test_submit_shows_on_reviewers_my_stuff_and_approve_closes_it(client, db, monkeypatch):
    sales, boss, job = _setup(client, db, monkeypatch)
    r = client.post(f"/jobs/{job['id']}/review", headers=sales, json={})
    assert r.status_code == 200, r.text
    review = r.json()
    assert review["note_type"] == "review" and review["review_status"] == "pending"
    assert review["assignee_email"] == "boss@example.com" and review["job_id"] == job["id"]

    # pressing it again while it waits does not stack a second one
    again = client.post(f"/jobs/{job['id']}/review", headers=sales, json={}).json()
    assert again["id"] == review["id"]

    mine = client.get("/notes", headers=boss).json()
    assert [n["id"] for n in mine if n["note_type"] == "review"] == [review["id"]]
    assert client.get("/notes/unread-count", headers=boss).json()["count"] == 1

    # only the reviewer answers
    assert client.post(f"/notes/{review['id']}/review", headers=sales, json={"decision": "approve"}).status_code == 403
    done = client.post(f"/notes/{review['id']}/review", headers=boss, json={"decision": "approve"}).json()
    assert done["review_status"] == "approved" and done["completed_at"]
    assert not [n for n in client.get("/notes", headers=boss).json() if n["note_type"] == "review"]
    # the submitter sees the answer as a reply
    sub = [n for n in client.get("/notes", headers=sales, params={"show_done": True}).json() if n["id"] == review["id"]][0]
    assert sub["replies"][-1]["body"] == "Approved" and sub["unread"]


def test_hold_stays_open_and_resubmit_goes_back_to_pending(client, db, monkeypatch):
    sales, boss, job = _setup(client, db, monkeypatch)
    review = client.post(f"/jobs/{job['id']}/review", headers=sales, json={"comment": "pricing check"}).json()
    held = client.post(f"/notes/{review['id']}/review", headers=boss, json={"decision": "hold", "comment": "tops missing"}).json()
    assert held["review_status"] == "hold" and held["completed_at"] is None
    assert client.get(f"/jobs/{job['id']}/review", headers=sales).json()["review_status"] == "hold"
    assert [n["id"] for n in client.get("/notes", headers=boss).json() if n["note_type"] == "review"] == [review["id"]]

    back = client.post(f"/jobs/{job['id']}/review", headers=sales, json={}).json()
    assert back["id"] == review["id"] and back["review_status"] == "pending"
    replies = [n for n in client.get("/notes", headers=boss).json() if n["id"] == review["id"]][0]["replies"]
    assert [r["body"] for r in replies] == ["Held for review: tops missing", "Resubmitted for review"]
    assert client.post(f"/notes/{review['id']}/review", headers=boss, json={"decision": "nope"}).status_code == 422
