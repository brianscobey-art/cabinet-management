from datetime import date

from app.field_measure import HousePlan, Template, _is_template, _parse_name, match_template


def _tpl(rel, **over):
    name = rel.split("/")[-1]
    info = _parse_name(rel, name, None)
    info.update(over)
    return Template(rel=rel, name=name, **info)


def test_parse_name_reads_series_swing_plan_and_date():
    info = _parse_name("DR Horton/DRH Pensacola/Floorplans/EX/EX4 Madison/Layout/EX4 Madison STD-R Layout 120525.pdf",
                       "EX4 Madison STD-R Layout 120525.pdf", None)
    assert info["series"] == "EX4"
    assert info["swing"] == "R"
    assert info["plan_tokens"] == ("madison",)
    assert info["version"] == "120525" and info["version_date"] == date(2025, 12, 5)
    assert info["division"] == "Pensacola"


def test_parse_name_handles_the_other_swing_spellings():
    assert _parse_name("x/Layouts/DRH4 Casey LH Layout.pdf", "DRH4 Casey LH Layout.pdf", None)["swing"] == "L"
    assert _parse_name("x/Layouts/DRH4 Madison R STD Layout.pdf", "DRH4 Madison R STD Layout.pdf", None)["swing"] == "R"
    assert _parse_name("x/Layouts/DRH2 Avery STD 042126.pdf", "DRH2 Avery STD 042126.pdf", None)["swing"] is None


def test_template_filter_skips_archives_tops_and_builder_plans():
    assert _is_template(("DR Horton", "Floorplans", "Horton", "DRH1 Alabaster STD", "Layouts", "DRH1 Alabaster STD-R 040126.pdf"),
                        "DRH1 Alabaster STD-R 040126.pdf")
    assert not _is_template(("DR Horton", "Floorplans", "Horton", "Archive", "Layouts", "DRH Alabaster STD-R.pdf"), "DRH Alabaster STD-R.pdf")
    assert not _is_template(("DR Horton", "Floorplans", "Horton", "X", "Plan", "Alabaster B46 RFE Master.pdf"), "Alabaster B46 RFE Master.pdf")
    assert not _is_template(("Century", "CC Roanoke", "Layouts", "Century Roanoke Tops-L 040825.pdf"), "Century Roanoke Tops-L 040825.pdf")


def test_match_prefers_exact_swing_then_division_and_rejects_other_family():
    tpls = [
        _tpl("DR Horton/DRH Pensacola/Floorplans/DRH/DRH4 Madison STD/DRH4 Madison L STD Layout.pdf"),
        _tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Madison 120325/Layouts/DRH2 Madison STD-L 030926.pdf"),
        _tpl("DR Horton/DRH Pensacola/Floorplans/EX/EX4 Madison/Layout/EX4 Madison STD-L Layout 120525.pdf"),
    ]
    plan = HousePlan(abbr="MADI", name="DRH2 Madison STD", swing="L", series="DRH2",
                     tokens=("madison",), division="Montgomery")
    m = match_template(plan, tpls)
    assert m.status == "ok" and m.template.rel.startswith("DR Horton/DRH Montgomery")
    # Express house must never get a Horton drawing even with the same plan name
    ex = HousePlan(abbr="MADI", name="EX4 Madison STD", swing="L", series="EX4", tokens=("madison",), division="Pensacola")
    assert match_template(ex, tpls).template.series == "EX4"


def test_own_division_opposite_hand_beats_another_divisions_exact_hand():
    """DRLB50-0063: Panama City EX1 Beau-R. Its own drawing exists only as L;
    Pensacola's EX4 Beau-R must NOT win just because the hand matches."""
    tpls = [
        _tpl("DR Horton/DRH Panama City/Floorplans/Express/EX1 Beau STD/Layouts/EX1 Beau, B1DRWS-L 060426.pdf"),
        _tpl("DR Horton/DRH Pensacola/Floorplans/EX/EX4 Beau/Layout/EX4 Beau STD-R 043026.pdf"),
        _tpl("DR Horton/DRH Montgomery/Flooprlans/Express/EX2 Beau STD 041626/Layouts/EX2 Beau, B1DRWS STD Layout 041626.pdf"),
    ]
    plan = HousePlan(abbr="BEAU", name="EX1 Beau, B1DRWS STD", swing="R", series="EX1",
                     tokens=("beau", "b1drws"), division="Panama City")
    m = match_template(plan, tpls)
    assert m.template.rel.startswith("DR Horton/DRH Panama City")
    assert m.status == "mirror" and "BEAU-L" in m.note and "Pensacola" not in m.note


def test_a_shared_option_code_never_matches_a_different_plan():
    """EX1 Walker, B1DRWS shares B1DRWS with EX1 Beau, B1DRWS -- not a Beau."""
    tpls = [
        _tpl("DR Horton/DRH Panama City/Floorplans/Express/EX1 Walker STD/Layouts/EX1 Walker ,B1DRWS STD 060426.pdf"),
        _tpl("DR Horton/DRH Panama City/Floorplans/Express/EX1 Beau STD/Layouts/EX1 Beau, B1DRWS-L 060426.pdf"),
    ]
    plan = HousePlan(abbr="BEAU", name="EX1 Beau, B1DRWS STD", swing="R", series="EX1",
                     tokens=("beau", "b1drws"), division="Panama City")
    m = match_template(plan, tpls)
    assert "Beau" in m.template.rel and m.status == "mirror"


def test_another_division_only_when_the_own_set_has_nothing_and_it_says_so():
    tpls = [_tpl("DR Horton/DRH Pensacola/Floorplans/EX/EX4 Beau/Layout/EX4 Beau STD-R 043026.pdf")]
    plan = HousePlan(abbr="BEAU", name="EX1 Beau STD", swing="R", series="EX1",
                     tokens=("beau",), division="Panama City")
    m = match_template(plan, tpls)
    assert m.status == "ok" and "Pensacola plan set" in m.note


def test_a_one_letter_typo_in_the_tracker_still_finds_the_plan():
    tpls = [_tpl("Century Complete/Plans/CC Roanoake 082626/Layouts/CC Roanoke 36in STD 071026.pdf"),
            _tpl("Century Complete/Plans/CC Beaumont 082625/Layouts/CC Beaumont 36in STD 071026.pdf")]
    plan = HousePlan(abbr="ROAN", name="CC Roanoake 36in STD", swing="L", series="CC",
                     tokens=("roanoake", "36in"), division=None)
    assert "Roanoke" in match_template(plan, tpls).template.rel


def test_a_job_file_among_the_templates_keeps_its_series():
    info = _parse_name("DR Horton/DROPE-3021 EX2 4EBF Cali, B1DRWS STD Layout 030926.pdf",
                       "DROPE-3021 EX2 4EBF Cali, B1DRWS STD Layout 030926.pdf", None)
    assert info["series"] == "EX2" and info["plan_tokens"][:2] == ("4ebf", "cali")


def test_plan_names_are_not_mistaken_for_divisions():
    info = _parse_name("Century Complete/Plans/CC Beaumont 082625/Layouts/CC Beaumont 36in STD 071026.pdf",
                       "CC Beaumont 36in STD 071026.pdf", None)
    assert info["division"] is None


def test_match_falls_back_to_the_opposite_hand_and_says_so():
    tpls = [_tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Harper/Layouts/DRH2 Harper STD-L 031226.pdf")]
    plan = HousePlan(abbr="HARP", name="DRH2 Harper STD", swing="R", series="DRH2", tokens=("harper",), division="Montgomery")
    m = match_template(plan, tpls)
    assert m.template is tpls[0] and m.status == "mirror" and "HARP-L" in m.note and "mirror" in m.note


def test_match_without_swing_takes_a_swingless_template_and_newest_version():
    tpls = [
        _tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Avery/Layouts/DRH2 Avery STD 112525.pdf"),
        _tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Avery/Layouts/DRH2 Avery STD 042126.pdf"),
    ]
    plan = HousePlan(abbr="AVER", name="DRH2 Avery STD", swing=None, series="DRH2", tokens=("avery",), division="Montgomery")
    assert match_template(plan, tpls).template.version == "042126"
