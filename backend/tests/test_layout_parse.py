"""Layout import rules found by checking 15 real layouts against their orders (11/5/26).

Inputs are pasted text, so no company PDFs live in the repo.
"""

from app.sterling_app.layout_parse import catalog_name, parse_layout

KNOWN = {
    "B24", "SB36", "VS27", "VS30", "VS36", "3VDB18", "BT9", "W3018", "W301815",
    "W3024", "W302415", "DCW2436", "LSB33", "U189024", "F642", "F342", "DWR3",
    "SCR", "SHM", "TKC", "OCM", "CM8", "BP9636",
}


def _lines(result):
    return {line["sku"]: line["qty"] for line in result["lines"]}


def test_drawn_2020_fillers_never_become_lines():
    r = parse_layout(text="B24\nBF3\nBF6\nVF3\nWF3\nAccessories\n2-F630\n", known_skus=KNOWN)
    assert _lines(r) == {"B24": 1, "F642": 2}


def test_2020_names_map_to_everluxe_catalog():
    text = "VSB30\nV2721\nVDB18\nB09L\nFDB09R\nWD2436\nW3018-15\nLS33-L\nU1890L\n"
    assert _lines(parse_layout(text=text, known_skus=KNOWN)) == {
        "VS30": 1, "VS27": 1, "3VDB18": 1, "BT9": 2, "DCW2436": 1,
        "W301815": 1, "LSB33": 1, "U189024": 1,
    }


def test_catalog_name_leaves_a_current_sku_alone():
    assert catalog_name("W3024", KNOWN) == "W3024"
    assert catalog_name("VSB36", KNOWN) == "VS36"


def test_trim_callouts_and_split_pieces():
    text = (
        "Accessories\n1-DWR3\n1-F63 6\n1-36x96 Back Panel\nStock\n"
        "4-S\n3/4\n3-BTK8\n3-SM10\n1-90 OCM\n3-CM10\n"
    )
    assert _lines(parse_layout(text=text, known_skus=KNOWN)) == {
        "DWR3": 1, "F642": 1, "BP9636": 1, "SCR": 4, "TKC": 3, "SHM": 3,
        "OCM": 1, "CM8": 4,  # 3 x 10' of crown = 30' = 4 sticks of 8'
    }


def test_hardware_callouts_count_pieces_and_header_names_style():
    text = "Hardware: 3910-SN\nB24\n3910-SN\nHardware\n34-Black Knobs\n"
    r = parse_layout(text=text, known_skus=KNOWN)
    assert r["hardware_pieces"] == 34
    assert r["hardware_style"] == "3910-SN"
    assert _lines(r) == {"B24": 1}


def test_room_tags_and_panel_pieces_are_not_cabinets():
    text = "Ba1\nBA2\nSB36\nFBP3636\nFBP3636\nAccessories\n1-BP9636\n"
    assert _lines(parse_layout(text=text, known_skus=KNOWN)) == {"SB36": 1, "BP9636": 1}


def test_panel_piece_without_a_back_panel_callout_is_kept_and_flagged():
    r = parse_layout(text="SB36\nPBP72\n", known_skus=KNOWN)
    assert _lines(r) == {"SB36": 1, "PBP72": 1}
    assert "PBP72" in r["unknown"]


def test_more_than_one_vendor_is_flagged():
    text = "Vendor: Ridgewood\nB15\nVendor: Everluxe\nB24\n"
    r = parse_layout(text=text, known_skus=KNOWN)
    assert any("more than one vendor" in w for w in r["warnings"])


# Rules found by checking 15 sold DR Horton jobs against their orders (11/6/26).

def test_lot_code_in_title_block_is_not_a_cabinet():
    text = "B24\nBUID: 268200185\nDRPF40-0185\nDRH2 Ole Southside STD\n"
    r = parse_layout(text=text, known_skus=KNOWN)
    assert _lines(r) == {"B24": 1}
    assert r["lot"] == "DRPF40-0185" and r["buid"] == "268200185"


def test_split_lumber_callout_is_lumber_not_lines():
    r = parse_layout(text="B24\nOther\n1-2\nx4-8\n1-1x4-8\n", known_skus=KNOWN)
    assert _lines(r) == {"B24": 1}
    assert r["lumber"] == {"2x4 (8')": 1, "1x4 (8')": 1}


def test_title_block_names_hardware_when_header_says_see_specs():
    paired = ("Hardware: See Specs\nB24\nBUID: 1\nDRLICR-0117\nEX2 Ozark STD\n"
              "Door Style\nShaker\nColor\nWhite\nHardware\n3910PC\n")
    r = parse_layout(text=paired, known_skus=KNOWN)
    assert r["hardware_style"] == "3910PC" and r["color"] == "White"
    grouped = ("Hardware: Pulls\nB24\nBUID: 1\nDRPF40-0185\nDRH2 Ole\n"
               "Door Style\nColor\nHardware\nShaker\nDove Gray\nMatte Black Pulls\n")
    r = parse_layout(text=grouped, known_skus=KNOWN)
    assert r["hardware_style"] == "MATTE BLACK PULLS" and r["color"] == "Dove Gray"
    caps = "B24\nBUID: 1\nDRWC-0008\nEX2 Lakeside STD\nDOOR STYLE\nShaker\nCOLOR\nWhite\nHARDWARE\n3910PC\n"
    assert parse_layout(text=caps, known_skus=KNOWN)["hardware_style"] == "3910PC"
