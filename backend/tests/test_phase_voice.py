from app import phase_voice as pv

ROWS = [
    {"job_id": 1, "job_code": "DRID60-0012", "lot_number": "12", "address": "105 Liberty Ln", "phase": "5"},
    {"job_id": 2, "job_code": "DRID60-0014", "lot_number": "014", "address": "109 Liberty Ln", "phase": "3"},
    {"job_id": 3, "job_code": "DRID60-0020", "lot_number": "20", "address": "121 Liberty Ln", "phase": None},
    {"job_id": 4, "job_code": "DRID60-0021", "lot_number": "21", "address": "123 Liberty Ln", "phase": "1"},
    {"job_id": 5, "job_code": "DRID60-0022", "lot_number": "22", "address": "125 Liberty Ln", "phase": "1"},
    {"job_id": 6, "job_code": "DRID60-0009", "lot_number": "9", "address": "90 Liberty Ln", "phase": "4.2"},
]


def got(text):
    return [(i["lot"], i["job_id"], i["phase"], i["ok"]) for i in pv.parse(text, ROWS)["items"]]


def test_basic_lots_and_phases():
    assert got("Lot 12 drywall hung, lot 14 framing complete") == [("12", 1, "6", True), ("14", 2, "4", True)]


def test_number_words_and_no_keyword():
    assert got("lot twelve tape and float. 14 framing") == [("12", 1, "7", True), ("14", 2, "3", True)]


def test_ranges_and_lists():
    assert got("lots 20 through 22 slab poured") == [("20", 3, "2", True), ("21", 4, "2", True), ("22", 5, "2", True)]
    assert got("lots 12, 14 and 20 textured") == [("12", 1, "8", True), ("14", 2, "8", True), ("20", 3, "8", True)]


def test_phase_number_and_same():
    assert got("lot 9 phase 4.3 lot 12 same") == [("9", 6, "4.3", True), ("12", 1, "5", True)]
    assert got("lot 9 phase four point four") == [("9", 6, "4.4", True)]


def test_problems_are_reported_not_guessed():
    out = pv.parse("lot 99 trim, lot 20 same, lot 12 drywall", ROWS)["items"]
    assert out[0]["problem"].startswith("no lot") and not out[0]["ok"]
    assert out[1]["problem"].startswith("said same") and not out[1]["ok"]
    assert out[2]["problem"].startswith("no phase heard") and not out[2]["ok"]


def test_house_number_fallback_and_repeat():
    assert got("123 paint") == [("123", 4, "10", True)]
    out = pv.parse("lot 12 trim lot 12 paint", ROWS)["items"]
    assert [i["ok"] for i in out] == [False, True] and out[1]["phase"] == "10"
