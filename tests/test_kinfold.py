import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import kinfold  # noqa: E402
from kinfold import (  # noqa: E402
    _ordinal,
    _removed,
    ahnentafel,
    common_ancestors,
    lint,
    main,
    parse,
    relationship,
    render_descendants,
    slot_completeness,
    stats,
    to_dot,
)

EXAMPLE = (ROOT / "examples" / "smith.fam").read_text(encoding="utf-8")


def errors_of(text):
    return [i for i in lint(parse(text)) if i.level == "error"]


def warnings_of(text):
    return [i for i in lint(parse(text)) if i.level == "warning"]


def test_example_file_is_clean():
    assert lint(parse(EXAMPLE)) == []


def test_impossible_date_is_reported_with_line_number():
    text = 'person a "A" born=1990-02-30\n'
    issues = parse(text).issues
    assert len(issues) == 1
    assert issues[0].line == 1
    assert "impossible date" in issues[0].message


def test_unknown_keyword_and_bad_sex_report_their_own_lines():
    text = 'person a "A"\nfamily b "B"\nperson c "C" sex=Q\n'
    issues = parse(text).issues
    assert [(i.line, i.level) for i in issues] == [(2, "error"), (3, "error")]
    assert "unknown keyword" in issues[0].message
    assert "sex must be" in issues[1].message


def test_duplicate_person_points_at_first_definition():
    issues = parse('person a "A"\nperson a "Again"\n').issues
    assert len(issues) == 1
    assert issues[0].line == 2
    assert "first defined on line 1" in issues[0].message


def test_unknown_parent_is_reported_on_the_parent_line():
    text = 'person c "C"\nparent ghost c\n'
    errors = errors_of(text)
    assert [(e.line, "ghost" in e.message) for e in errors] == [(2, True)]


def test_self_parent_is_an_error():
    text = 'person a "A"\nparent a a\n'
    assert any("own parent" in e.message for e in errors_of(text))


def test_ancestry_loop_is_detected():
    text = 'person a "A"\nperson b "B"\nparent a b\nparent b a\n'
    loops = [e for e in errors_of(text) if "ancestry loop" in e.message]
    assert loops, "expected a loop error"


def test_third_parent_is_an_error():
    text = (
        'person p1 "P1" born=1950\nperson p2 "P2" born=1950\nperson p3 "P3" born=1950\n'
        'person c "C" born=1980\nparent p1 c\nparent p2 c\nparent p3 c\n'
    )
    assert any("at most two" in e.message for e in errors_of(text))


def test_child_born_before_parent_is_an_error_and_small_gap_is_a_warning():
    text = (
        'person old "Old" born=1950\nperson young "Young" born=1990\n'
        'person kid "Kid" born=1960\nparent young kid\nparent old young\n'
    )
    assert any("before parent young" in e.message for e in errors_of(text))
    gap = 'person p "P" born=2000\nperson c "C" born=2005\nparent p c\n'
    assert any("only 5 years older" in w.message for w in warnings_of(gap))


def test_died_before_born_is_an_error():
    text = 'person a "A" born=1950 died=1940\n'
    assert any("before being born" in e.message for e in errors_of(text))


def test_siblings_and_half_siblings():
    tree = parse(EXAMPLE)
    assert relationship(tree, "gus", "hana").text == "Gus Smith and Hana Smith are siblings"
    text = (
        'person m "M" born=1950\nperson f1 "F1" born=1948\nperson f2 "F2" born=1948\n'
        'person x "X" born=1975\nperson y "Y" born=1977\n'
        'parent m x\nparent f1 x\nparent m y\nparent f2 y\n'
    )
    half = relationship(parse(text), "x", "y")
    assert half.text == "X and Y are half-siblings"


def test_first_cousins_once_removed():
    tree = parse(EXAMPLE)
    rel = relationship(tree, "jo", "ivo")
    assert rel.text == "Jo Smith and Ivo Smith are first cousins once removed"
    assert rel.common == "ann"
    assert (rel.a_gens, rel.b_gens) == (3, 2)


def test_uncle_and_grandparent_labels():
    tree = parse(EXAMPLE)
    assert relationship(tree, "dee", "gus").text == "Dee Smith is Gus Smith's uncle/aunt"
    assert relationship(tree, "ann", "gus").text == "Ann Smith is Gus Smith's grandparent"


def test_unrelated_people_have_no_relationship():
    text = 'person a "A"\nperson b "B"\n'
    assert relationship(parse(text), "a", "b") is None


def test_common_ancestors_sorted_closest_first():
    rows = common_ancestors(parse(EXAMPLE), "gus", "ivo")
    assert [r[0] for r in rows] == ["ann", "bob"]
    assert rows[0][1:] == (2, 2)


def test_ahnentafel_uses_sex_for_father_and_mother_slots():
    numbers = dict((n, pid) for n, pid in ahnentafel(parse(EXAMPLE), "gus", 2))
    assert numbers == {1: "gus", 2: "cy", 3: "fran", 4: "bob", 5: "ann",
                       6: "hal", 7: "eve"}


def test_completeness_counts_unknown_slots():
    tree = parse(EXAMPLE)
    rows = slot_completeness(tree, "gus", 3)
    assert rows[0] == (1, 2, 2)
    assert rows[1] == (2, 4, 4)
    assert rows[2] == (3, 0, 8)


def test_stats_summary():
    s = stats(parse(EXAMPLE))
    assert s["people"] == 11
    assert s["founders"] == 4
    assert s["deepest"] == 3
    assert s["spouse_pairs"] == 3
    assert s["no_death_date"] == 7


def test_descendants_are_indented_and_depth_limited():
    lines = render_descendants(parse(EXAMPLE), "ann", 2)
    assert lines[0].startswith("ann ")
    assert any(line.startswith("  cy ") for line in lines)
    assert any(line.startswith("    gus ") for line in lines)
    assert not any(line.startswith("      ") for line in lines)


def test_dot_export_has_parent_and_spouse_edges():
    dot = to_dot(parse(EXAMPLE))
    assert dot.startswith("digraph kinfold {")
    assert '"cy" -> "gus";' in dot
    assert '"cy" -> "fran" [dir=none, style=dashed];' in dot


def test_ordinal_and_removal_words():
    assert _ordinal(1) == "first"
    assert _ordinal(3) == "third"
    assert _ordinal(11) == "11th"
    assert _ordinal(21) == "21st"
    assert _removed(0) == ""
    assert _removed(3) == " 3 times removed"


def test_cli_lint_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean.fam"
    clean.write_text(EXAMPLE, encoding="utf-8")
    assert main(["lint", str(clean)]) == 0

    warned = tmp_path / "warned.fam"
    warned.write_text('person p "P" born=2000\nperson c "C" born=2005\nparent p c\n', encoding="utf-8")
    assert main(["lint", str(warned)]) == 0
    assert main(["lint", str(warned), "--strict"]) == 1

    broken = tmp_path / "broken.fam"
    broken.write_text('person a "A"\nparent a nobody\n', encoding="utf-8")
    assert main(["lint", str(broken)]) == 1
    assert "2: error" in capsys.readouterr().out


def test_cli_refuses_to_query_a_broken_file_and_unknown_ids(tmp_path, capsys):
    broken = tmp_path / "broken.fam"
    broken.write_text('person a "A" born=1990-02-31\n', encoding="utf-8")
    assert main(["stats", str(broken)]) == 2
    assert "impossible date" in capsys.readouterr().err

    good = tmp_path / "good.fam"
    good.write_text(EXAMPLE, encoding="utf-8")
    assert main(["rel", str(good), "ann", "zed"]) == 2
    assert "no person with id 'zed'" in capsys.readouterr().err


def test_cli_rel_prints_relationship_and_common_ancestor(tmp_path, capsys):
    good = tmp_path / "good.fam"
    good.write_text(EXAMPLE, encoding="utf-8")
    assert main(["rel", str(good), "gus", "ivo"]) == 0
    out = capsys.readouterr().out
    assert "Gus Smith and Ivo Smith are first cousins." in out
    assert "Closest common ancestor: Ann Smith" in out


def test_cli_rejects_out_of_range_generations(tmp_path, capsys):
    good = tmp_path / "good.fam"
    good.write_text(EXAMPLE, encoding="utf-8")
    assert main(["ancestors", str(good), "gus", "--gens", "0"]) == 2
    assert "--gens must be between" in capsys.readouterr().err
