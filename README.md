# Kinfold

**Offline family-tree checker and explorer, driven by one plain-text `.fam` file.**

Kinfold reads your family in a readable text file, catches impossible records with exact line numbers, and answers the questions people actually ask: how are these two people related, who are the ancestors, which branches are missing, and what does the tree look like as a graph. It runs on Python 3's standard library, with no accounts, no servers, and no network calls.

## Features

- **Plain-text format** with `person`, `parent` and `spouse` lines. Diff it, version it, and edit it in any editor.
- **Line-numbered parse errors** for unknown keywords, bad IDs, duplicate people, bad dates, unbalanced quotes and unknown options.
- **Calendar-checked dates** in `YYYY`, `YYYY-MM` or `YYYY-MM-DD` form. `1990-02-30` is rejected.
- **Full lint pass** for impossible records: unknown IDs, self-parenting, ancestry loops, more than two parents, children born before parents, and death before birth.
- **Soft warnings** for suspicious but possible data, such as a parent only a few years older than the child, a child born after a parent's death, or a repeated parent or spouse pair.
- **Relationship finder** that names the link between any two people (siblings, half-siblings, aunt/uncle, grandparent, first cousins twice removed, and so on), using the closest common ancestor.
- **Common-ancestor listing** for any two people, with the generation count from each side.
- **Ancestor listing** grouped by generation, with a depth limit.
- **Descendant tree** printed as an indented outline.
- **Ahnentafel numbering** (Sosa-Stradonitz: father 2n, mother 2n+1), using recorded sex and falling back to declaration order.
- **Completeness report** that counts filled ancestor positions per generation, so you can see the research gaps.
- **Tree statistics**: people, founders, deepest ancestry, spouse pairs, living-or-unknown count, and average age at death.
- **Name search** across names and IDs.
- **Graphviz DOT export** for drawing the tree with `dot -Tsvg`.
- **CI exit codes**: `lint` returns 1 on errors, and `--strict` also fails on warnings.

## Quick start

Kinfold needs Python 3.8 or newer. There is nothing to install.

Save this as `family.fam`:

```text
person ann  "Ann Smith"   born=1928-02-14 died=2011-07-09 sex=F
person bob  "Bob Smith"   born=1925-11-02 died=1999-01-30 sex=M
person cy   "Cy Smith"    born=1952-05-20 sex=M
person dee  "Dee Smith"   born=1955-01-09 sex=F
person gus  "Gus Smith"   born=1978-09-30 sex=M
person ivo  "Ivo Smith"   born=1984-12-01 sex=M

parent ann cy
parent bob cy
parent ann dee
parent bob dee
parent cy gus
parent dee ivo
```

Then ask it questions:

```console
$ python3 kinfold.py lint family.fam
0 error(s), 0 warning(s) in family.fam

$ python3 kinfold.py rel family.fam gus ivo
Gus Smith and Ivo Smith are first cousins.
Closest common ancestor: Ann Smith (2 generation(s) from gus, 2 from ivo)
```

The repository also ships a larger sample, `examples/smith.fam`, with three marriages and a grandchild:

```console
$ python3 kinfold.py stats examples/smith.fam
People:                 11
Founders (no parents):  4
Deepest ancestry:       3 generation(s)
Spouse pairs:           3
No death date recorded: 7
Average age at death:   75.0 years (from 4 people with both dates)

$ python3 kinfold.py rel examples/smith.fam dee gus
Dee Smith is Gus Smith's uncle/aunt.
Closest common ancestor: Ann Smith (1 generation(s) from dee, 2 from gus)
```

When a file has problems, every command refuses to run until they are fixed, and the errors point at their lines. Save this as `broken.fam`:

```text
person ann "Ann Smith" born=1928-02-30
person cy  "Cy Smith"  born=1952-05-20
parent cy cy
parent bob cy
```

```console
$ python3 kinfold.py lint broken.fam
broken.fam:1: error: impossible date '1928-02-30'
broken.fam:3: error: cy cannot be their own parent
broken.fam:4: error: unknown person id 'bob'
3 error(s), 0 warning(s) in broken.fam
```

## The `.fam` format

Each line is one of three kinds. Blank lines and `#` comments are ignored. Quote names that contain spaces.

| Line | Meaning |
| --- | --- |
| `person ID "Name" [born=DATE] [died=DATE] [sex=M\|F\|X]` | A person. IDs use letters, digits, `-` or `_`. |
| `parent PARENT CHILD` | `PARENT` is a parent of `CHILD`. Give each child at most two. |
| `spouse A B [married=DATE]` | `A` and `B` were or are married or partnered. |

`DATE` is `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. Partial dates are fine, and checks use the year.

## Commands

```text
python3 kinfold.py lint FILE [--strict]           check everything; exit 1 on errors
python3 kinfold.py rel FILE A B                   how A and B are related
python3 kinfold.py common FILE A B                every common ancestor
python3 kinfold.py ancestors FILE ID [--gens N]   ancestors grouped by generation
python3 kinfold.py descendants FILE ID [--gens N] indented descendant tree
python3 kinfold.py ahnen FILE ID [--gens N]       Sosa-Stradonitz numbers
python3 kinfold.py completeness FILE ID [--gens N] filled ancestor positions
python3 kinfold.py stats FILE                     summary of the whole tree
python3 kinfold.py find FILE TEXT                 search names and IDs
python3 kinfold.py dot FILE [-o OUT.dot]          Graphviz DOT export
```

`--gens` defaults to 12 and must be between 1 and 12.

Exit codes: `0` success, `1` lint found errors (or warnings with `--strict`), `2` the file could not be read, contains errors for a query command, or the query named an unknown person.

To draw the tree:

```console
$ python3 kinfold.py dot examples/smith.fam -o smith.dot
$ dot -Tsvg smith.dot -o smith.svg
```

## How to run

Run the CLI directly from the repository root:

```console
$ python3 kinfold.py --help
```

Kinfold is a single file, `kinfold.py`, that you can copy anywhere.

## How to test

The tests use pytest, the one third-party package this project uses.

```console
$ python3 -m pip install pytest
$ python3 -m pytest -q
```

The suite covers parsing and line-numbered errors, every lint rule, relationship naming (siblings, half-siblings, uncles, grandparents and cousins), common ancestors, ahnentafel numbering, completeness counts, statistics, DOT export and the CLI exit codes.

## Project layout

```text
kinfold.py              the whole program: parser, lint, queries and CLI
examples/smith.fam      a clean sample family
tests/test_kinfold.py   pytest suite
```

## Limits

- Relationship names describe blood and marriage links as recorded. Adoption, step-parents and half-relations that are not recorded as parent lines are not inferred.
- Half-siblings are people who share exactly one recorded parent.
- Ahnentafel numbers follow recorded sex. When sex is unknown or conflicting, the first parent listed is taken as the father.
