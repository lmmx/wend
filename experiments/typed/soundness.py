"""Does a static type ever claim more than the runtime declares?

Generates random chains of real wend operations (declarations, bind,
rebase, tag, derivations, joins), runs each statement at runtime, and has
Pyright and ty reveal the type of every intermediate expression. For each
statement it compares:

- the static atoms with ``facts(e).atoms`` (soundness: static ⊆ runtime);
- the static kind with ``facts(e).kind`` (soundness: Unknown, or equal);
- a runtime rejection (joining below a File raises) with the static type
  ``JoinBelowFile``.

    uv run python experiments/typed/soundness.py [programs] [seed]

Prints a summary table; exits non-zero on any unsound statement.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from wend._experimental import typed as W


PYRIGHT = "pyright@1.1.407"
TY = "ty@0.0.90"

PRELUDE = """\
from typing import Final, Literal, Never, reveal_type
from wend._experimental.typed import (
    Absent, AnyPath, Creatable, Dir, Exists, File, IsFile, Listable, P, Param,
    PathExpr, Readable, SubPath, T, Under, Writable,
)
root, name, idx = Param("root"), Param("name"), Param("idx", type=int)
STATIC: Final = "/srv/static"
"""

# Every atom an expression can declare, and a function demanding it.
ATOMS = [
    *(
        f"{p}{a}"
        for p in ("", "post_")
        for a in ("read", "write", "create", "list", "exists", "absent", "file", "dir")
    ),
    "Under[str]",
    "Under['/srv/static']",
    "Under['/tmp']",
]


def demand(atom: str) -> str:
    return "demand_" + re.sub(r"\W", "_", atom)


def demand_type(atom: str) -> str:
    if atom == "Under[str]":
        return "Under[str]"
    if atom.startswith("Under["):
        return f'Under[Literal["{atom[7:-2]}"]]'
    return f'Literal["{atom}"]'


DEMANDS = (
    "".join(
        f"def {demand(a)}(p: PathExpr[{demand_type(a)}]) -> None: ...\n" for a in ATOMS
    )
    + "def demand_IsFile(p: PathExpr[Never, IsFile]) -> None: ...\n"
)

STARTS = [
    ('P(root) / "raw" / T(t"{name}.csv")', {"root", "name"}),
    ("P(root) / name", {"root", "name"}),
    ('P(STATIC) / AnyPath("rel")', {"rel", "STATIC"}),
    ('P(root) / SubPath("sub") / "f.txt"', {"root", "sub"}),
    ('T(t"{root}/x_{idx:03d}.bin")', {"root", "idx"}),
    ('P("/tmp") / name', {"name"}),
]

PRE = ["Readable", "Writable", "Creatable", "Listable", "Exists", "Absent"]
KINDS = ["File", "Dir"]


CONTRADICTIONS = [
    {"Exists", "Absent"},
    {"File", "Dir"},
    {"Absent", "Readable"},
    {"Absent", "Listable"},
    {"File", "Listable"},
]


def conditions(rng: random.Random, params: set[str]) -> str:
    conds = rng.sample(PRE, rng.randint(0, 3))
    consistent = rng.random() < 0.7
    unders = ["Under(STATIC)", 'Under("/tmp")'] + (
        ["Under(P(root))"] if "root" in params else []
    )
    if "STATIC" in params:
        unders += ["Under(STATIC)"] * 3
    if rng.random() < 0.35:
        conds.append(rng.choice(unders))
    rng.shuffle(conds)
    if rng.random() < 0.5:
        k = rng.choice(KINDS)
        # Kind first (the typed form) most of the time, anywhere otherwise.
        conds.insert(0 if rng.random() < 0.75 else rng.randint(0, len(conds)), k)
    if consistent:  # most declarations make sense; the rest test rejection
        for pair in CONTRADICTIONS:
            if pair <= set(conds):
                conds.remove(sorted(pair)[1])
    return ", ".join(conds)


def op(rng: random.Random, var: str, params: set[str]) -> tuple[str, set[str]]:
    r = rng.random()
    if r < 0.30:
        return f"{var}.requires({conditions(rng, params)})", params
    if r < 0.45:
        return f"{var}.ensures({conditions(rng, params)})", params
    if r < 0.52 and "name" in params:
        return f'{var}.bind(name="a")', params - {"name"}
    if r < 0.57 and "root" in params:
        return f'{var}.bind(root="/d")', params - {"root"}
    if r < 0.63 and "root" in params:
        return f'{var}.rebase(P(root), P("/elsewhere"))', params - {"root"}
    if r < 0.66 and "STATIC" in params:
        # moves a declared base when it lies under the old one
        return f'{var}.rebase(P(STATIC), P("/moved"))', params - {"STATIC"}
    if r < 0.67:
        return f'{var}.tag(k="v")', params
    if r < 0.70:
        return f"P({var})", params
    derived = [
        (f"{var}.parent", params),
        (f'{var}.with_suffix(".x")', params),
        (f'{var}.with_name("n.txt")', params),
        (f'{var}.sibling("s.json")', params),
        (f'{var} / "x"', params),
        (f'{var}.joinpath("y")', params),
    ]
    return rng.choice(derived)


TARGETED = [
    # containment, then a rebase that moves the declared base
    [
        'P(STATIC) / AnyPath("rel")',
        "{v}.requires(Under(STATIC), Readable)",
        '{v}.rebase(P(STATIC), P("/moved"))',
    ],
    [
        'P(STATIC) / AnyPath("rel")',
        "{v}.requires(Readable, Under(STATIC))",
        '{v}.bind(rel="a")',
        '{v}.rebase(P(STATIC), P("/moved"))',
    ],
    [
        'P(root) / AnyPath("rel")',
        "{v}.requires(Under(STATIC), Exists)",
        '{v}.rebase(P(root), P("/moved"))',
    ],
    [
        'P(root) / AnyPath("rel")',
        "{v}.requires(Under(P(root)), Readable)",
        '{v}.bind(root="/srv")',
        '{v}.rebase(P("/srv"), P("/moved"))',
    ],
    # a file required, a directory ensured
    [
        "P(root) / name",
        "{v}.requires(File, Exists)",
        "{v}.ensures(Dir, Exists)",
        '{v}.bind(root="/d")',
    ],
]


def generate(n: int, seed: int) -> list[list[tuple[str, str]]]:
    rng = random.Random(seed)
    programs = []
    for t, chain in enumerate(TARGETED):
        stmts = [(f"t{t}_0", chain[0])]
        for j, step in enumerate(chain[1:], 1):
            stmts.append((f"t{t}_{j}", step.format(v=stmts[-1][0])))
        programs.append(stmts)
    for i in range(n):
        start, params = rng.choice(STARTS)
        stmts = [(f"v{i}_0", start)]
        for j in range(1, rng.randint(2, 6)):
            expr, params = op(rng, stmts[-1][0], params)
            stmts.append((f"v{i}_{j}", expr))
        programs.append(stmts)
    return programs


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


def runtime(programs):
    """For each statement: ("ok", facts), ("raised", exception name) or
    ("skipped", None) after an earlier statement of the program raised."""
    out = {}
    base: dict = {}
    exec(
        PRELUDE.replace(
            "from typing import Final, reveal_type\n", "from typing import Final\n"
        ),
        base,
    )
    for stmts in programs:
        ns = dict(base)
        dead = False
        for var, expr in stmts:
            if dead:
                out[var] = ("skipped", None)
                continue
            try:
                value = eval(expr, ns)
            except Exception as e:  # noqa: BLE001
                out[var] = ("raised", type(e).__name__)
                dead = True
                continue
            ns[var] = value
            out[var] = (
                ("ok", W.facts(value))
                if isinstance(value, W.PathExpr)
                else ("other", type(value).__name__)
            )
    return out


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------


def source(programs) -> tuple[str, dict[int, str]]:
    lines = PRELUDE.splitlines()
    where = {}
    for stmts in programs:
        for var, expr in stmts:
            lines.append(f"{var} = {expr}")
            lines.append(f"reveal_type({var})")
            where[len(lines)] = var
    return "\n".join(lines) + "\n", where


def parse_type(t: str) -> tuple[frozenset[str], str] | str:
    t = t.replace('"', "'").strip()
    if t.startswith("JoinBelowFile"):
        return "JoinBelowFile"
    m = re.fullmatch(r"PathExpr\[(.*), (\w+)\]", t)
    if not m:
        return t
    caps, kind = m[1], m[2]
    if re.search(
        r"(^|[\s|\[])(Unknown|Any)($|[\s|\]])", re.sub(r"Under\[[^\]]*\]\]?", "", caps)
    ):
        return (
            "top"  # Unknown or Any among the declarations satisfies every requirement
        )
    atoms: set[str] = set()
    for u in re.findall(r"Under\[Literal\[([^\]]*)\]\]", caps):
        atoms |= {f"Under[{a.strip()}]" for a in u.split(",")}
    if "Under[str]" in caps:
        atoms.add("Under[str]")
    rest = re.sub(r"Under\[[^\]]*\]\]?", "", caps)
    for lit in re.findall(r"Literal\[([^\]]*)\]", rest):
        atoms |= {a.strip().strip("'") for a in lit.split(",")}
    return frozenset(atoms), kind


def pyright_types(path: Path, where: dict[int, str]) -> dict[str, str]:
    out = subprocess.run(
        [
            "uvx",
            "-q",
            PYRIGHT,
            "--outputjson",
            "--pythonpath",
            sys.executable,
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    types = {}
    for d in json.loads(out.stdout)["generalDiagnostics"]:
        m = re.match(r'Type of "([vt]\d+_\d+)" is "(.*)"$', d["message"])
        if m:
            types[m[1]] = m[2]
    return types


def ty_types(path: Path, where: dict[int, str]) -> dict[str, str]:
    out = subprocess.run(
        [
            "uvx",
            "-q",
            TY,
            "check",
            "--python",
            sys.executable,
            "--output-format",
            "concise",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    types = {}
    for line in out.stdout.splitlines():
        m = re.match(
            r".+?:(\d+):\d+: info\[revealed-type\] Revealed type: `(.*)`$", line
        )
        if m and int(m[1]) in where:
            types[where[int(m[1])]] = m[2]
    return types


# ---------------------------------------------------------------------------


def judge(rt, st) -> str:
    """unsound / exact / weaker / rejected-agree / rejected-miss / skipped."""
    status, val = rt
    if status == "skipped":
        return "skipped"
    s = parse_type(st) if st is not None else None
    if status == "raised":
        return "rejected-agree" if s == "JoinBelowFile" else f"rejected-miss:{val}"
    if status != "ok":
        return "other"
    if s == "top":
        return "unsound"
    if not isinstance(s, tuple):
        return f"unparsed:{st}"
    atoms, kind = s
    f = val
    if not atoms <= f.atoms:
        return "unsound"
    if kind not in ("Unspecified", f.kind.__name__):
        return "unsound"
    exact = atoms == f.atoms and kind == f.kind.__name__
    return "exact" if exact else "weaker"


def context_source(programs, rt, static_types, rng):
    """Each runtime-valid expression, inline, where up to three atoms it does
    not declare are demanded (must be errors) and one atom its static type
    has is demanded (must not be)."""
    lines = (PRELUDE + DEMANDS).splitlines()
    must_fail, must_pass = set(), set()
    for stmts in programs:
        for var, expr in stmts:
            status, f = rt[var]
            if status != "ok":
                continue
            absent = [a for a in ATOMS if a not in f.atoms]
            for a in rng.sample(absent, min(3, len(absent))):
                lines.append(f"{demand(a)}({expr})")
                must_fail.add(len(lines))
            if f.kind.__name__ != "IsFile":
                lines.append(f"demand_IsFile({expr})")
                must_fail.add(len(lines))
            st = parse_type(static_types.get(var, ""))
            if isinstance(st, tuple) and st[0]:
                lines.append(f"{demand(rng.choice(sorted(st[0])))}({expr})")
                must_pass.add(len(lines))
    # the expressions refer to earlier variables: define them first
    defs = [
        f"{var} = {expr}"
        for stmts in programs
        for var, expr in stmts
        if rt[var][0] == "ok"
    ]
    text = (
        "\n".join(
            lines[: len((PRELUDE + DEMANDS).splitlines())]
            + defs
            + lines[len((PRELUDE + DEMANDS).splitlines()) :]
        )
        + "\n"
    )
    shift = len(defs)
    return text, {n + shift for n in must_fail}, {n + shift for n in must_pass}


def error_lines(checker: str, path: Path) -> set[int]:
    if checker == "pyright":
        out = subprocess.run(
            [
                "uvx",
                "-q",
                PYRIGHT,
                "--outputjson",
                "--pythonpath",
                sys.executable,
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        return {
            d["range"]["start"]["line"] + 1
            for d in json.loads(out.stdout)["generalDiagnostics"]
            if d["severity"] == "error"
        }
    out = subprocess.run(
        [
            "uvx",
            "-q",
            TY,
            "check",
            "--python",
            sys.executable,
            "--output-format",
            "concise",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return {
        int(m[1]) for m in re.finditer(r"^.+?:(\d+):\d+: error\[", out.stdout, re.M)
    }


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    programs = generate(n, seed)
    rt = runtime(programs)
    text, where = source(programs)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "generated.py"
        f.write_text(text)
        static = {"pyright": pyright_types(f, where), "ty": ty_types(f, where)}
    bad = 0
    examples: dict[str, list[str]] = {}
    for checker, types in static.items():
        tally = Counter()
        for stmts in programs:
            for var, expr in stmts:
                v = judge(rt[var], types.get(var))
                key = v.split(":")[0]
                tally[key] += 1
                if (
                    key in ("unsound", "unparsed", "rejected-miss")
                    and len(examples.setdefault(f"{checker} {key}", [])) < 5
                ):
                    examples[f"{checker} {key}"].append(
                        f"{var} = {expr}  -> static {types.get(var)!r}, runtime {rt[var]}"
                    )
        bad += tally["unsound"]
        total = sum(tally.values()) - tally["skipped"]
        print(
            f"{checker}: {total} statements  "
            + "  ".join(f"{k}={v}" for k, v in sorted(tally.items()))
        )
    for k, v in examples.items():
        print(f"\n{k}:")
        for line in v:
            print("  ", line)
    # Context: the same expressions inline, where an undeclared atom is demanded.
    rng = random.Random(seed + 1)
    text, must_fail, must_pass = context_source(programs, rt, static["pyright"], rng)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "context.py"
        f.write_text(text)
        lines = text.splitlines()
        for checker in ("pyright", "ty"):
            errs = error_lines(checker, f)
            accepted = sorted(must_fail - errs)
            rejected = sorted(must_pass & errs)
            stray = sorted(errs - must_fail - must_pass)
            bad += len(accepted)
            print(
                f"{checker} in context: {len(must_fail)} undeclared demands, accepted {len(accepted)}; "
                f"{len(must_pass)} declared demands, rejected {len(rejected)}; other errors {len(stray)}"
            )
            for n in accepted[:5]:
                print("   ACCEPTED:", lines[n - 1])
            for n in (rejected + stray)[:3]:
                print("   error:", lines[n - 1])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
