#!/usr/bin/env python3
"""Kinfold: offline family-tree checker and explorer for plain-text .fam files.

A .fam file has three kinds of line. Blank lines and # comments are ignored.

    person ann "Ann Smith" born=1928-02-14 died=2011-07-09 sex=F
    parent ann cy
    spouse ann bob married=1948-06-12

Run `python3 kinfold.py --help` for the commands. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

MAX_GENERATIONS = 12
MIN_PARENT_AGE = 12
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
SEXES = {"M", "F", "X"}
PERSON_OPTIONS = {"born", "died", "sex"}
SPOUSE_OPTIONS = {"married"}
ORDINALS = ["first", "second", "third", "fourth", "fifth",
            "sixth", "seventh", "eighth", "ninth", "tenth"]


class FamError(ValueError):
    """A problem that stops a line, or a command, from being used."""


@dataclass
class Issue:
    line: int
    level: str  # "error" or "warning"
    message: str

    def __str__(self):
        return f"{self.line}: {self.level}: {self.message}"


@dataclass
class Person:
    id: str
    name: str
    line: int
    born: tuple | None = None  # (year, month, day); month and day may be None
    died: tuple | None = None
    sex: str = "X"
    parents: list = field(default_factory=list)
    children: list = field(default_factory=list)


@dataclass
class Tree:
    people: dict = field(default_factory=dict)
    parent_edges: list = field(default_factory=list)  # (line, parent, child)
    spouses: list = field(default_factory=list)  # (line, a, b, married)
    issues: list = field(default_factory=list)

    def add(self, line, level, message):
        self.issues.append(Issue(line, level, message))


@dataclass
class Relationship:
    a: str
    b: str
    common: str
    a_gens: int
    b_gens: int
    text: str


# ---------- dates and small formatting helpers ----------

def parse_date(text):
    """Parse YYYY, YYYY-MM or YYYY-MM-DD into (year, month, day)."""
    match = DATE_RE.match(text)
    if not match:
        raise FamError(f"bad date {text!r}; use YYYY, YYYY-MM or YYYY-MM-DD")
    year, month, day = (int(group) if group else None for group in match.groups())
    try:
        date(year, month or 1, day or 1)
    except ValueError:
        raise FamError(f"impossible date {text!r}") from None
    return year, month, day


def format_years(person):
    born = str(person.born[0]) if person.born else "?"
    if person.died:
        return f"{born}-{person.died[0]}"
    return f"{born}-" if person.born else "?"


def describe(person):
    return f"{person.id:<12} {person.name} ({format_years(person)})"


def _ordinal(n):
    if n <= len(ORDINALS):
        return ORDINALS[n - 1]
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _removed(n):
    if n == 0:
        return ""
    if n == 1:
        return " once removed"
    if n == 2:
        return " twice removed"
    return f" {n} times removed"


def _ancestor_term(n):
    if n == 1:
        return "parent"
    if n == 2:
        return "grandparent"
    return "great-" * (n - 2) + "grandparent"


def _collateral_term(n):
    return "great-" * (n - 2) + "uncle/aunt"


# ---------- parsing ----------

def _options(tokens, allowed):
    options = {}
    for token in tokens:
        if "=" not in token:
            raise FamError(f"expected key=value, got {token!r}")
        key, value = token.split("=", 1)
        key = key.lower()
        if key not in allowed:
            raise FamError(f"unknown option {key!r}")
        if key in options:
            raise FamError(f"option {key!r} given twice")
        options[key] = value
    return options


def _add_person(tree, lineno, args):
    if len(args) < 2:
        raise FamError("person needs an id and a name")
    pid, name, *rest = args
    if not ID_RE.match(pid):
        raise FamError(f"bad id {pid!r}; use letters, digits, - or _")
    if pid in tree.people:
        raise FamError(f"duplicate person {pid!r} (first defined on line {tree.people[pid].line})")
    options = _options(rest, PERSON_OPTIONS)
    sex = options.get("sex", "X").upper()
    if sex not in SEXES:
        raise FamError(f"sex must be M, F or X, not {sex!r}")
    born = parse_date(options["born"]) if "born" in options else None
    died = parse_date(options["died"]) if "died" in options else None
    tree.people[pid] = Person(pid, name, lineno, born, died, sex)


def _add_parent(tree, lineno, args):
    if len(args) != 2:
        raise FamError("parent needs exactly two ids: parent PARENT CHILD")
    tree.parent_edges.append((lineno, args[0], args[1]))


def _add_spouse(tree, lineno, args):
    if len(args) < 2 or "=" in args[0] or "=" in args[1]:
        raise FamError("spouse needs two ids: spouse A B [married=DATE]")
    options = _options(args[2:], SPOUSE_OPTIONS)
    married = parse_date(options["married"]) if "married" in options else None
    tree.spouses.append((lineno, args[0], args[1], married))


def _link(tree):
    """Resolve parent and spouse lines against the person table."""
    for lineno, parent, child in tree.parent_edges:
        unknown = [pid for pid in (parent, child) if pid not in tree.people]
        if unknown:
            tree.add(lineno, "error", f"unknown person id {unknown[0]!r}")
        elif parent == child:
            tree.add(lineno, "error", f"{child} cannot be their own parent")
        elif parent in tree.people[child].parents:
            tree.add(lineno, "warning", f"{parent} is already listed as a parent of {child}")
        else:
            tree.people[child].parents.append(parent)
            tree.people[parent].children.append(child)
    seen_pairs = set()
    for lineno, a, b, _married in tree.spouses:
        unknown = [pid for pid in (a, b) if pid not in tree.people]
        if unknown:
            tree.add(lineno, "error", f"unknown person id {unknown[0]!r}")
        elif a == b:
            tree.add(lineno, "error", f"{a} cannot be their own spouse")
        elif frozenset((a, b)) in seen_pairs:
            tree.add(lineno, "warning", f"{a} and {b} are already spouses")
        else:
            seen_pairs.add(frozenset((a, b)))


def parse(text):
    """Turn .fam text into a Tree. Problems are recorded in tree.issues, not raised."""
    tree = Tree()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        try:
            tokens = shlex.split(raw, comments=True)
        except ValueError as exc:
            tree.add(lineno, "error", f"unbalanced quote ({exc})")
            continue
        if not tokens:
            continue
        keyword, args = tokens[0].lower(), tokens[1:]
        try:
            if keyword == "person":
                _add_person(tree, lineno, args)
            elif keyword == "parent":
                _add_parent(tree, lineno, args)
            elif keyword == "spouse":
                _add_spouse(tree, lineno, args)
            else:
                raise FamError(f"unknown keyword {tokens[0]!r}; expected person, parent or spouse")
        except FamError as exc:
            tree.add(lineno, "error", str(exc))
    _link(tree)
    return tree


# ---------- checks ----------

def _find_loops(tree):
    issues = []
    state = {}  # id -> "visiting" or "done"
    path = []

    def visit(pid):
        state[pid] = "visiting"
        path.append(pid)
        for parent in tree.people[pid].parents:
            if state.get(parent) == "visiting":
                loop = path[path.index(parent):] + [parent]
                issues.append(Issue(tree.people[pid].line, "error",
                                    "ancestry loop: " + " -> ".join(loop)))
            elif parent not in state:
                visit(parent)
        path.pop()
        state[pid] = "done"

    for pid in tree.people:
        if pid not in state:
            visit(pid)
    return issues


def lint(tree):
    """Return every problem with the tree, sorted by line number."""
    issues = list(tree.issues)
    for person in tree.people.values():
        if len(person.parents) > 2:
            issues.append(Issue(person.line, "error",
                                f"{person.id} has {len(person.parents)} parents; at most two are allowed"))
        if person.born and person.died and person.died[0] < person.born[0]:
            issues.append(Issue(person.line, "error",
                                f"{person.id} died in {person.died[0]}, before being born in {person.born[0]}"))
        for pid in person.parents:
            parent = tree.people[pid]
            if parent.born and person.born:
                gap = person.born[0] - parent.born[0]
                if gap < 0:
                    issues.append(Issue(person.line, "error",
                                        f"{person.id} born {person.born[0]}, before parent {pid} ({parent.born[0]})"))
                elif gap < MIN_PARENT_AGE:
                    issues.append(Issue(person.line, "warning",
                                        f"parent {pid} is only {gap} years older than {person.id}"))
            if parent.died and person.born and person.born[0] > parent.died[0]:
                issues.append(Issue(person.line, "warning",
                                    f"{person.id} born {person.born[0]}, after parent {pid} died in {parent.died[0]}"))
    issues.extend(_find_loops(tree))
    return sorted(issues, key=lambda issue: (issue.line, issue.level != "error", issue.message))


# ---------- graph queries ----------

def ancestors(tree, pid, max_gen=MAX_GENERATIONS):
    """Map each ancestor of pid to its shortest generation distance. pid itself is excluded."""
    distance = {}
    queue = deque([(pid, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth == max_gen:
            continue
        for parent in tree.people[current].parents:
            if parent != pid and parent not in distance:
                distance[parent] = depth + 1
                queue.append((parent, depth + 1))
    return distance


def common_ancestors(tree, a, b):
    """Return [(ancestor_id, gens_from_a, gens_from_b)] sorted from closest to furthest."""
    from_a = {a: 0, **ancestors(tree, a)}
    from_b = {b: 0, **ancestors(tree, b)}
    shared = [(c, from_a[c], from_b[c]) for c in from_a if c in from_b]
    return sorted(shared, key=lambda row: (row[1] + row[2], row[1], row[0]))


def _describe_pair(tree, a, b, da, db):
    na, nb = tree.people[a].name, tree.people[b].name
    if da == 0 and db == 0:
        return f"{na} and {nb} are the same person"
    if db == 0:
        return f"{nb} is {na}'s {_ancestor_term(da)}"
    if da == 0:
        return f"{na} is {nb}'s {_ancestor_term(db)}"
    if da == 1 and db == 1:
        same_parents = set(tree.people[a].parents) == set(tree.people[b].parents)
        return f"{na} and {nb} are {'siblings' if same_parents else 'half-siblings'}"
    if db == 1:
        return f"{nb} is {na}'s {_collateral_term(da)}"
    if da == 1:
        return f"{na} is {nb}'s {_collateral_term(db)}"
    degree = min(da, db) - 1
    return f"{na} and {nb} are {_ordinal(degree)} cousins{_removed(abs(da - db))}"


def relationship(tree, a, b):
    """Describe how a and b are related through their closest common ancestor, or None."""
    shared = common_ancestors(tree, a, b)
    if not shared:
        return None
    common, da, db = shared[0]
    return Relationship(a, b, common, da, db, _describe_pair(tree, a, b, da, db))


def ahnentafel(tree, root, gens):
    """Return [(number, person_id)] using Sosa-Stradonitz numbering (father 2n, mother 2n+1)."""
    rows = []
    queue = deque([(root, 1, 0)])
    while queue:
        pid, number, depth = queue.popleft()
        rows.append((number, pid))
        if depth == gens:
            continue
        father, mother = _father_and_mother(tree, pid)
        if father:
            queue.append((father, 2 * number, depth + 1))
        if mother:
            queue.append((mother, 2 * number + 1, depth + 1))
    return sorted(rows)


def _father_and_mother(tree, pid):
    """Use recorded sex first; unknown or conflicting sex falls back to declaration order."""
    parents = tree.people[pid].parents[:2]
    father = mother = None
    for parent in parents:
        sex = tree.people[parent].sex
        if sex == "M" and father is None:
            father = parent
        elif sex == "F" and mother is None:
            mother = parent
    for parent in parents:
        if parent in (father, mother):
            continue
        if father is None:
            father = parent
        elif mother is None:
            mother = parent
    return father, mother


def slot_completeness(tree, root, gens):
    """Count filled ancestor positions per generation: [(gen, filled, total)]."""
    filled = [0] * (gens + 1)
    total = [0] * (gens + 1)

    def walk(pid, depth):
        if depth == gens:
            return
        parents = tree.people[pid].parents[:2] if pid else []
        for slot in range(2):
            total[depth + 1] += 1
            parent = parents[slot] if slot < len(parents) else None
            if parent:
                filled[depth + 1] += 1
            walk(parent, depth + 1)

    walk(root, 0)
    return [(g, filled[g], total[g]) for g in range(1, gens + 1)]


def render_descendants(tree, root, max_depth=MAX_GENERATIONS):
    lines = []
    on_path = set()

    def walk(pid, depth):
        lines.append("  " * depth + describe(tree.people[pid]))
        if depth == max_depth:
            return
        on_path.add(pid)
        for child in tree.people[pid].children:
            if child not in on_path:
                walk(child, depth + 1)
        on_path.discard(pid)

    walk(root, 0)
    return lines


def _generation_depth(tree, pid, memo, active):
    if pid in memo:
        return memo[pid]
    if pid in active:  # ancestry loops are reported by lint
        return 0
    active.add(pid)
    value = max((1 + _generation_depth(tree, p, memo, active)
                 for p in tree.people[pid].parents), default=0)
    active.discard(pid)
    memo[pid] = value
    return value


def stats(tree):
    people = list(tree.people.values())
    memo, active = {}, set()
    deepest = max((_generation_depth(tree, p.id, memo, active) for p in people), default=0)
    ages = [p.died[0] - p.born[0] for p in people
            if p.born and p.died and p.died[0] >= p.born[0]]
    return {
        "people": len(people),
        "founders": sum(1 for p in people if not p.parents),
        "deepest": deepest,
        "spouse_pairs": len({frozenset((a, b)) for _line, a, b, _married in tree.spouses}),
        "no_death_date": sum(1 for p in people if not p.died),
        "average_age": (sum(ages) / len(ages)) if ages else None,
        "ages_counted": len(ages),
    }


def _dot_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def to_dot(tree):
    """Graphviz DOT: boxes for people, arrows for parent to child, dashed lines for spouses."""
    lines = ["digraph kinfold {", "  rankdir=TB;", '  node [shape=box, fontname="Helvetica"];']
    people = sorted(tree.people.values(), key=lambda p: p.id)
    for person in people:
        label = f"{_dot_escape(person.name)}\\n{format_years(person)}"
        lines.append(f'  "{person.id}" [label="{label}"];')
    for person in people:
        for parent in person.parents:
            lines.append(f'  "{parent}" -> "{person.id}";')
    for _line, a, b, _married in tree.spouses:
        lines.append(f'  "{a}" -> "{b}" [dir=none, style=dashed];')
    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------- command line ----------

def _person(tree, pid):
    if pid not in tree.people:
        raise FamError(f"no person with id {pid!r}")
    return pid


def _cmd_lint(tree, args):
    issues = lint(tree)
    for issue in issues:
        print(f"{args.file}:{issue}")
    errors = sum(1 for i in issues if i.level == "error")
    warnings = len(issues) - errors
    print(f"{errors} error(s), {warnings} warning(s) in {args.file}")
    return 1 if errors or (args.strict and warnings) else 0


def _cmd_rel(tree, args):
    rel = relationship(tree, _person(tree, args.a), _person(tree, args.b))
    if rel is None:
        print(f"{args.a} and {args.b} share no recorded ancestor.")
        return 0
    print(rel.text + ".")
    if args.a != args.b:
        common = tree.people[rel.common]
        print(f"Closest common ancestor: {common.name} ({rel.a_gens} generation(s) from {args.a}, "
              f"{rel.b_gens} from {args.b})")
    return 0


def _cmd_common(tree, args):
    rows = common_ancestors(tree, _person(tree, args.a), _person(tree, args.b))
    if not rows:
        print("No common ancestors recorded.")
        return 0
    print(f"Common ancestors of {args.a} and {args.b}:")
    for pid, da, db in rows:
        print(f"  {describe(tree.people[pid])}  [{da} and {db} generation(s)]")
    return 0


def _cmd_ancestors(tree, args):
    root = _person(tree, args.id)
    found = sorted(ancestors(tree, root, args.gens).items(), key=lambda row: (row[1], row[0]))
    print(f"Ancestors of {root} ({len(found)} found):")
    for pid, depth in found:
        print(f"  gen {depth:>2}  {describe(tree.people[pid])}")
    if not found:
        print("  No recorded ancestors.")
    return 0


def _cmd_descendants(tree, args):
    root = _person(tree, args.id)
    for line in render_descendants(tree, root, args.gens):
        print(line)
    return 0


def _cmd_ahnen(tree, args):
    root = _person(tree, args.id)
    print(f"Ahnentafel for {root}:")
    for number, pid in ahnentafel(tree, root, args.gens):
        print(f"  {number:>4}. {describe(tree.people[pid])}")
    return 0


def _cmd_completeness(tree, args):
    root = _person(tree, args.id)
    print(f"Ancestor positions known for {root}, up to {args.gens} generation(s):")
    all_filled = all_total = 0
    for gen, filled, total in slot_completeness(tree, root, args.gens):
        all_filled += filled
        all_total += total
        print(f"  gen {gen:>2}: {filled:>4} of {total:<4} ({100 * filled / total:5.1f}%)")
    print(f"  overall: {all_filled} of {all_total} ({100 * all_filled / all_total:.1f}%)")
    return 0


def _cmd_stats(tree, args):
    s = stats(tree)
    print(f"People:                 {s['people']}")
    print(f"Founders (no parents):  {s['founders']}")
    print(f"Deepest ancestry:       {s['deepest']} generation(s)")
    print(f"Spouse pairs:           {s['spouse_pairs']}")
    print(f"No death date recorded: {s['no_death_date']}")
    if s["average_age"] is None:
        print("Average age at death:   n/a")
    else:
        print(f"Average age at death:   {s['average_age']:.1f} years "
              f"(from {s['ages_counted']} people with both dates)")
    return 0


def _cmd_find(tree, args):
    needle = args.text.lower()
    matches = [p for p in sorted(tree.people.values(), key=lambda p: p.id)
               if needle in p.name.lower() or needle in p.id.lower()]
    for person in matches:
        print(describe(person))
    if not matches:
        print(f"No one matches {args.text!r}.")
    return 0


def _cmd_dot(tree, args):
    dot = to_dot(tree)
    if args.out:
        Path(args.out).write_text(dot, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(dot)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="kinfold", description="Offline family-tree checker for .fam files.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, help_text, handler, *positional, gens=False):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("file", help="path to a .fam file")
        for pos in positional:
            p.add_argument(pos)
        if gens:
            p.add_argument("--gens", type=int, default=MAX_GENERATIONS,
                           help=f"generations to follow (1-{MAX_GENERATIONS}, default {MAX_GENERATIONS})")
        p.set_defaults(handler=handler)
        return p

    lint_parser = add("lint", "check the file; exit 1 on errors", _cmd_lint)
    lint_parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    add("rel", "say how two people are related", _cmd_rel, "a", "b")
    add("common", "list every common ancestor of two people", _cmd_common, "a", "b")
    add("ancestors", "list a person's ancestors by generation", _cmd_ancestors, "id", gens=True)
    add("descendants", "print a person's descendants as an indented tree", _cmd_descendants, "id", gens=True)
    add("ahnen", "print Sosa-Stradonitz (ahnentafel) numbers", _cmd_ahnen, "id", gens=True)
    add("completeness", "report how many ancestor positions are filled", _cmd_completeness, "id", gens=True)
    add("stats", "summarise the whole tree", _cmd_stats)
    add("find", "search people by name or id", _cmd_find, "text")
    dot_parser = add("dot", "export Graphviz DOT", _cmd_dot)
    dot_parser.add_argument("-o", "--out", help="write to this file instead of stdout")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    gens = getattr(args, "gens", None)
    if gens is not None and not 1 <= gens <= MAX_GENERATIONS:
        print(f"kinfold: --gens must be between 1 and {MAX_GENERATIONS}", file=sys.stderr)
        return 2
    try:
        tree = parse(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        print(f"kinfold: cannot read {args.file}: {exc}", file=sys.stderr)
        return 2

    if args.command == "lint":
        return _cmd_lint(tree, args)

    errors = [issue for issue in lint(tree) if issue.level == "error"]
    if errors:
        for issue in errors:
            print(f"{args.file}:{issue}", file=sys.stderr)
        print("kinfold: fix the errors above first (kinfold lint shows everything)", file=sys.stderr)
        return 2
    try:
        return args.handler(tree, args)
    except FamError as exc:
        print(f"kinfold: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
