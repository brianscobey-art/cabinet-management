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


def test_match_reports_swing_gap_instead_of_mirroring():
    tpls = [_tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Harper/Layouts/DRH2 Harper STD-L 031226.pdf")]
    plan = HousePlan(abbr="HARP", name="DRH2 Harper STD", swing="R", series="DRH2", tokens=("harper",), division="Montgomery")
    m = match_template(plan, tpls)
    assert m.template is None and m.status == "swing" and "HARP-L" in m.note


def test_match_without_swing_takes_a_swingless_template_and_newest_version():
    tpls = [
        _tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Avery/Layouts/DRH2 Avery STD 112525.pdf"),
        _tpl("DR Horton/DRH Montgomery/Flooprlans/DRH/DRH2 Avery/Layouts/DRH2 Avery STD 042126.pdf"),
    ]
    plan = HousePlan(abbr="AVER", name="DRH2 Avery STD", swing=None, series="DRH2", tokens=("avery",), division="Montgomery")
    assert match_template(plan, tpls).template.version == "042126"
