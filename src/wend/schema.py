"""Directory schemas: declare a project's layout once, then bind, validate and scaffold it.

A schema is a class whose attributes are entries, each a relative path (a
string, t-string or expression) that names a file or a directory::

    from wend import Dir, File, Param, T
    from wend.schema import Tree

    index = Param("index", type=int)

    class MLProject(Tree):
        data = Dir("data")
        raw = Dir(data / "raw")
        processed = Dir(data / "processed")
        models = Dir("models")
        checkpoints = File(models / T(t"model-{index:03d}.pt"), many=True)
        config = File("config.yaml")

    project = MLProject("/srv/project")
    project.config            # PathExpr('/srv/project/config.yaml', requires=(File, Exists))
    project.validate()        # a Report: missing, extra, misfiled, wrong-kind ... paths
    project.scaffold()        # creates the directories (an explicit effect)

An entry's *cardinality* says how many paths matching it each directory that
matches its parent holds: exactly one by default, ``optional=True`` for at
most one, ``many=True`` for any number, both for "zero or more". Entries are
expressions, so one can be built from another (``data / "raw"``) and the
relation is kept: a bound schema's ``raw`` has ``data`` as its base.

`from_inferred` turns an inferred `wend.infer.Schema` into a schema class, and
`Tree.source` prints a schema as Python, so a layout can be inferred from a
tree, reviewed, edited and kept as code. See docs/SEMANTICS.md §12.
"""

from __future__ import annotations

import enum
import keyword
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, overload

from ._expr import REL, Field, HeadParam, Part, PathExpr, Seg, Splice, _coerce, _Rel
from ._params import Kind, Param
from .conditions import Dir, Exists, File


if TYPE_CHECKING:
    from .infer import Schema as InferredSchema


__all__ = ["Cardinality", "Entry", "Problem", "Report", "Tree", "from_inferred"]


class Cardinality(enum.Enum):
    """How many paths matching an entry each directory matching its parent
    holds, as UML multiplicities.

    The lower bound is zero when ``optional``, and the upper bound is more
    than one when ``many``. A schema entry declares the two flags; an
    inferred layout (`wend.infer.Layout`) observes them, and reports its
    cardinality with this same type.
    """

    ONE = "1"
    OPTIONAL = "0..1"
    AT_LEAST_ONE = "1..*"
    MANY = "0..*"

    @classmethod
    def of(cls, *, optional: bool, many: bool) -> Cardinality:
        """The cardinality with these bounds."""
        if many:
            return cls.MANY if optional else cls.AT_LEAST_ONE
        return cls.OPTIONAL if optional else cls.ONE


_FRAGMENT_HEADS = (Kind.AUTO, Kind.SEGMENT, Kind.SUBPATH)


class Entry:
    """One declared path of a schema: made by ``File(path, ...)`` or
    ``Dir(path, ...)``. On a bound schema instance, the attribute is the
    entry's expression under the instance's root."""

    def __init__(
        self,
        path: Any,
        kind: str,
        *,
        optional: bool = False,
        many: bool = False,
        open: bool = False,
    ) -> None:
        expr = path.expr if isinstance(path, Entry) else _coerce(path, at_head=True)
        h = expr.head
        if isinstance(h, HeadParam) and h.param.kind in _FRAGMENT_HEADS:
            # Under the root, a leading parameter is what joining makes it: a
            # segment, or a SubPath splice.
            first: Part = (
                Splice(h.param)
                if h.param.kind is Kind.SUBPATH
                else Seg((Field(h.param, role="segment"),))
            )
            expr = PathExpr(REL, (first, *expr.parts))
        if not isinstance(expr.head, _Rel):
            raise ValueError(
                f"A schema entry is relative to the schema's root, not {expr.pattern!r}"
            )
        if not expr.parts:
            raise ValueError("A schema entry needs at least one segment")
        if open and kind != "dir":
            raise ValueError("Only a directory can be open")
        self.expr = expr
        self.kind = kind
        self.optional = optional
        self.many = many
        self.open = open
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type) -> Entry: ...
    @overload
    def __get__(self, instance: Tree, owner: type) -> PathExpr: ...
    def __get__(self, instance: Tree | None, owner: type) -> Entry | PathExpr:
        if instance is None:
            return self
        return instance._path(self)

    def __truediv__(self, other: Any) -> PathExpr:
        """The entry's expression joined with ``other``, for building one
        entry from another: ``raw = Dir(data / "raw")``."""
        return self.expr / other

    @property
    def cardinality(self) -> Cardinality:
        return Cardinality.of(optional=self.optional, many=self.many)

    @property
    def condition(self) -> Any:
        return File if self.kind == "file" else Dir

    def __repr__(self) -> str:
        extra = (
            "" if self.cardinality is Cardinality.ONE else f", {self.cardinality.value}"
        )
        opened = ", open" if self.open else ""
        return f"{self.condition!r}({self.expr.pattern!r}{extra}{opened})"


# ---------------------------------------------------------------------------
# Validation reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """One way a tree departs from its schema.

    ``kind`` is one of:
    - ``"missing"``: an entry has fewer paths than its cardinality allows (``path`` is where one was expected);
    - ``"too-many"``: a directory holds more than one path of a single-path entry;
    - ``"wrong-kind"``: a path matches an entry but is a file where a directory is declared, or the reverse;
    - ``"extra"``: a path no entry describes (the topmost one, not each path below it);
    - ``"misfiled"``: an extra path whose name matches an entry, somewhere else.

    ``entry`` names the entry concerned (for an extra path, the nearest
    directory entry above it, if any).
    """

    kind: str
    path: str
    entry: str | None
    detail: str = ""

    def __repr__(self) -> str:
        entry = f" [{self.entry}]" if self.entry else ""
        detail = f": {self.detail}" if self.detail else ""
        return f"<{self.kind} {self.path!r}{entry}{detail}>"


class Report:
    """The result of `Tree.validate`: every problem found, every entry's
    matches, and the paths more than one entry matches (``overlaps``, which
    a schema may intend: a literal exception beside a general pattern)."""

    def __init__(
        self,
        root: str,
        problems: list[Problem],
        matches: dict[str, list[Any]],
        overlaps: dict[str, list[str]] | None = None,
    ) -> None:
        self.root = root
        self.problems = problems
        self.matches = matches
        self.overlaps = overlaps or {}

    @property
    def ok(self) -> bool:
        return not self.problems

    def __bool__(self) -> bool:
        return self.ok

    def of(self, kind: str) -> list[Problem]:
        return [p for p in self.problems if p.kind == kind]

    def __repr__(self) -> str:
        if self.ok:
            n = sum(map(len, self.matches.values()))
            return (
                f"Report({self.root!r}: ok, {n} paths in {len(self.matches)} entries)"
            )
        counts = Counter(p.kind for p in self.problems)
        head = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        lines = [f"Report({self.root!r}: {head})"]
        lines += [f"  {p!r}" for p in self.problems[:50]]
        if len(self.problems) > 50:
            lines.append(f"  ... {len(self.problems) - 50} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class Tree:
    """Base class of directory schemas (see the module docstring).

    Subclass it with `Entry` attributes (``File(...)``, ``Dir(...)``).
    ``ignore`` lists patterns, relative to the root, whose paths (and
    everything below them) validation does not look at; with ``hidden =
    False`` it does not look at names starting with ``.`` either.
    """

    entries: ClassVar[dict[str, Entry]] = {}
    ignore: ClassVar[tuple[Any, ...]] = ()
    hidden: ClassVar[bool] = True

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        entries: dict[str, Entry] = {}
        for klass in reversed(cls.__mro__):
            for k, v in vars(klass).items():
                if isinstance(v, Entry):
                    entries[k] = v
        cls.entries = entries

    def __init__(self, root: Any, /, **bindings: Any) -> None:
        self.root = _coerce(root, at_head=True)
        self.bindings = bindings
        self._cache: dict[int, PathExpr] = {}

    def __repr__(self) -> str:
        extra = "".join(f", {k}={v!r}" for k, v in self.bindings.items())
        return f"{type(self).__name__}({self.root.pattern!r}{extra})"

    # -- binding --------------------------------------------------------------

    def _bare(self, expr: PathExpr) -> PathExpr:
        """``expr`` under the root, following the joins that built it from
        other entries, so the relations between entries carry over."""
        key = id(expr)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        d = expr.derivation
        out: PathExpr | None = None
        if d is not None and d.op == "join":
            base = d.args[0]
            if any(e.expr is base for e in self.entries.values()):
                rel = expr.base_rel
                assert rel is not None
                out = self._bare(base) / rel
        if out is None:
            out = self.root / expr
        self._cache[key] = out
        return out

    def _path(self, entry: Entry) -> PathExpr:
        e = self._bare(entry.expr)
        names = e.param_names & self.bindings.keys()
        if names:
            e = e.bind({k: self.bindings[k] for k in names})
        conds = [entry.condition]
        if entry.cardinality is Cardinality.ONE and not entry.expr.param_names:
            conds.append(Exists)
        return e.requires(*conds)

    def paths(self) -> dict[str, PathExpr]:
        """Every entry's expression under this root."""
        return {k: self._path(e) for k, e in self.entries.items()}

    # -- validation -----------------------------------------------------------

    def validate(self) -> Report:
        """Compare the tree on disk with the schema, now (an effect).

        Every problem is reported, not just the first. The tree is observed
        as `infer` observes it: real directories are descended, a symlinked
        directory is neither descended nor reported as extra (an entry can
        still match it), and a symlink counts as a file or a directory by
        what it points to.
        """
        root = self.root.render(self.bindings)
        problems: list[Problem] = []
        matches: dict[str, list[Any]] = {}
        owners: dict[str, list[str]] = defaultdict(list)
        if not os.path.isdir(root):
            return Report(root, [Problem("missing", root, None, "the root")], {})
        ignored = self._ignored(root)
        for name, entry in self.entries.items():
            e = self._unconditioned(entry)
            # A symlink is judged by its target here, though never followed.
            want_dir = entry.kind == "dir"
            found = [
                m
                for m in e.glob()
                if os.path.isdir(m.path) == want_dir
                and not _under_any(m.path, ignored)
                and (self.hidden or not _is_hidden(m.path, root))
            ]
            matches[name] = found
            for m in found:
                owners[m.path].append(name)
        overlaps = {p: names for p, names in sorted(owners.items()) if len(names) > 1}
        strays = self._extra(root, owners, ignored)
        occupied = {p.path for p in strays if p.kind == "wrong-kind"}
        for name, entry in self.entries.items():
            e = self._unconditioned(entry)
            problems += [
                p
                for p in self._count(name, entry, e, matches[name])
                if p.path not in occupied
            ]
        problems += strays
        return Report(root, problems, matches, overlaps)

    def _unconditioned(self, entry: Entry) -> PathExpr:
        e = self._bare(entry.expr)
        names = e.param_names & self.bindings.keys()
        return e.bind({k: self.bindings[k] for k in names}) if names else e

    def _ignored(self, root: str) -> list[str]:
        out: list[str] = []
        for pattern in self.ignore:
            e = self.root / _coerce(pattern, at_head=True)
            names = e.param_names & self.bindings.keys()
            if names:
                e = e.bind({k: self.bindings[k] for k in names})
            out += [m.path for m in e.glob()]
        return out

    def _count(
        self, name: str, entry: Entry, e: PathExpr, found: list[Any]
    ) -> list[Problem]:
        lo = 0 if entry.optional else 1
        hi = None if entry.many else 1
        parent = e.parent
        if parent.param_names:
            dirs = [m.path for m in parent.glob(kind="dir")]
        else:
            p = parent.render()
            dirs = [p] if os.path.isdir(p) else []
        counts = Counter(os.path.dirname(m.path) or "." for m in found)
        # The lower bound asks for a match at or below each parent directory:
        # the same as directly in it when the entry has a fixed depth, and the
        # reading a recursive (SubPath) parent needs, where a directory may
        # hold only subdirectories.
        reached: set[str] = set()
        for m in found:
            p = os.path.dirname(m.path)
            while p and p not in reached:
                reached.add(p)
                up = os.path.dirname(p)
                if up == p:
                    break
                p = up
        out: list[Problem] = []
        if not dirs and lo and not parent.param_names and not e.param_names:
            out.append(Problem("missing", e.render(), name))
        for d in dirs:
            c = counts.get(d, 0)
            if lo and d not in reached:
                last = PathExpr(REL, (e.parts[-1],)).pattern
                where = e.render() if not e.param_names else f"{d}/{last}"
                out.append(Problem("missing", where, name))
            if hi is not None and c > hi:
                out.append(Problem("too-many", d, name, f"{c} paths, at most {hi}"))
        return out

    def _extra(
        self, root: str, owners: Mapping[str, list[str]], ignored: list[str]
    ) -> list[Problem]:
        expected: set[str] = set()
        for path in owners:
            expected.update(_ancestors(path, root))
        for entry in self.entries.values():
            prefix = self._static_prefix(entry)
            if (
                prefix is not None
            ):  # its directories are expected, even when it is missing
                expected.update(_ancestors(prefix, root))
        open_dirs = {
            m
            for name, entry in self.entries.items()
            if entry.open
            for m in owners_of(owners, name)
        }
        dir_entries = {
            path: names[0]
            for path, names in owners.items()
            if self.entries[names[0]].kind == "dir"
        }
        out: list[Problem] = []
        for dirpath, dirnames, filenames in os.walk(root):
            keep = []
            for d in sorted(dirnames):
                p = os.path.join(dirpath, d)
                if p in ignored or p in open_dirs or (not self.hidden and d[0] == "."):
                    continue  # its contents are not described
                if os.path.islink(p):
                    continue  # an alias: not descended, not reported
                if p not in owners and p not in expected:
                    if self._observable(p):
                        out.append(self._stray(p, "dir", dirpath, dir_entries))
                    continue  # report the topmost stray path only
                keep.append(d)
            dirnames[:] = keep
            for f in sorted(filenames):
                p = os.path.join(dirpath, f)
                if p in owners or p in expected or p in ignored:
                    continue
                if not self.hidden and f[0] == ".":
                    continue
                out.append(self._stray(p, "file", dirpath, dir_entries))
        return out

    def _observable(self, d: str) -> bool:
        """Whether ``infer`` would observe anything at or below ``d``: a file,
        or an empty directory (a directory holding only symlinked
        directories, which are not descended, holds nothing observable)."""
        for dirpath, dirnames, filenames in os.walk(d):
            if not self.hidden:
                dirnames[:] = [x for x in dirnames if x[0] != "."]
                filenames = [x for x in filenames if x[0] != "."]
            if filenames or not dirnames:
                return True
        return False

    def _stray(
        self, path: str, kind: str, parent: str, dir_entries: Mapping[str, str]
    ) -> Problem:
        for ename, entry in self.entries.items():
            if entry.kind == kind:
                continue
            try:
                hit = self._unconditioned(entry).match(path)
            except Exception:  # noqa: BLE001 - ambiguity or non-invertible: no claim
                hit = None
            if hit is not None:
                want = "a directory" if entry.kind == "dir" else "a file"
                return Problem("wrong-kind", path, ename, f"expected {want}")
        name = os.path.basename(path)
        for ename, entry in self.entries.items():
            last = entry.expr.parts[-1]
            if entry.kind != kind or not isinstance(last, Seg):
                continue
            try:
                hit = PathExpr(REL, (last,)).match(name)
            except Exception:  # noqa: BLE001 - ambiguity or non-invertible: no claim
                hit = None
            if hit is not None:
                return Problem(
                    "misfiled", path, ename, f"named like {entry.expr.pattern!r}"
                )
        above = _nearest(parent, dir_entries)
        return Problem("extra", path, above)

    def _static_prefix(self, entry: Entry) -> str | None:
        """The rendered literal path of an entry with no parameters."""
        e = self._unconditioned(entry)
        if e.param_names:
            return None
        return e.render()

    # -- scaffolding ----------------------------------------------------------

    def scaffold(self, *, files: bool = False, dry_run: bool = False) -> list[Path]:
        """Create the schema's directories under the root (an effect), and,
        with ``files=True``, an empty file for each required file entry.

        An entry with unbound parameters is created once per combination of
        their declared ``choices``, and skipped if one has none. Existing
        paths are left alone; nothing is overwritten. Returns the paths
        created (or, with ``dry_run``, that would be).
        """
        created: list[Path] = []
        seen: set[str] = set()

        def make_dir(p: str) -> None:
            missing = []
            a = p
            while a and a not in seen and not os.path.exists(a):
                missing.append(a)
                a = os.path.dirname(a)
            for a in reversed(missing):
                if not dry_run:
                    os.mkdir(a)
                created.append(Path(a))
                seen.add(a)

        for entry in self.entries.values():
            e = self._unconditioned(entry)
            for env in _choice_envs(e):
                p = e.render(env)
                if entry.kind == "dir":
                    make_dir(p)
                    continue
                make_dir(os.path.dirname(p) or ".")
                if files and not entry.optional and p not in seen:
                    seen.add(p)
                    if dry_run:
                        if not os.path.exists(p):
                            created.append(Path(p))
                        continue
                    try:
                        os.close(os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                    except FileExistsError:
                        continue
                    created.append(Path(p))
        return created

    # -- source ---------------------------------------------------------------

    @classmethod
    def source(cls, name: str | None = None) -> str:
        """The schema as Python source: parameter declarations, then a class."""
        name = name or cls.__name__
        params: dict[str, Param] = {}
        for entry in cls.entries.values():
            params.update(entry.expr.params)
        # Variables for the parameters, not shadowed by entries in the class body.
        taken = set(cls.entries) | {"Tree", "T", "File", "Dir"}
        var: dict[str, str] = {}
        used: set[str] = set()
        decls = []
        for p in sorted(params.values(), key=lambda p: p.name):
            v = _ident(p.name)
            while v in taken:
                v += "_"
            taken.add(v)
            var[p.name] = v
            src, names = _param_source(p)
            used |= names
            decls.append(f"{v} = {src}")
        body = []
        for ename, entry in cls.entries.items():
            args = [_expr_source(entry.expr, var)]
            if args[0].startswith("T("):
                used.add("T")
            if entry.optional:
                args.append("optional=True")
            if entry.many:
                args.append("many=True")
            if entry.open:
                args.append("open=True")
            used.add(repr(entry.condition))
            body.append(f"    {ename} = {entry.condition!r}({', '.join(args)})")
        lines = [
            f"from wend import {', '.join(sorted(used))}",
            "from wend.schema import Tree",
        ]
        if decls:
            lines += ["", "", *decls]
        lines += ["", "", f"class {name}(Tree):"]
        if cls.ignore:
            shown = ", ".join(
                repr(_coerce(x, at_head=True).pattern) for x in cls.ignore
            )
            lines.append(f"    ignore = ({shown},)")
        if not cls.hidden:
            lines.append("    hidden = False")
        lines += body
        if not cls.entries:
            lines.append("    pass")
        return "\n".join(lines) + "\n"


def owners_of(owners: Mapping[str, list[str]], name: str) -> Iterator[str]:
    return (p for p, names in owners.items() if name in names)


def _ancestors(path: str, root: str) -> list[str]:
    out = []
    p = os.path.dirname(path)
    while p and p != root and p.startswith(root) and p != os.path.dirname(p):
        out.append(p)
        p = os.path.dirname(p)
    return out


def _is_hidden(path: str, root: str) -> bool:
    rel = os.path.relpath(path, root)
    return any(
        part.startswith(".") and part not in (".", "..") for part in rel.split("/")
    )


def _under_any(path: str, dirs: list[str]) -> bool:
    return any(path == d or path.startswith(d.rstrip("/") + "/") for d in dirs)


def _nearest(parent: str, dir_entries: Mapping[str, str]) -> str | None:
    p = parent
    while p:
        if p in dir_entries:
            return dir_entries[p]
        up = os.path.dirname(p)
        if up == p:
            return None
        p = up
    return None


def _choice_envs(e: PathExpr) -> list[dict[str, Any]]:
    """Every combination of the declared choices of ``e``'s parameters, or
    none if one of them has no choices."""
    params = list(e.params.values())
    if any(p.choices is None for p in params):
        return []
    names = [p.name for p in params]
    pools = [sorted(p.choices, key=repr) for p in params]  # type: ignore[arg-type]
    return [dict(zip(names, combo, strict=True)) for combo in product(*pools)]


# ---------------------------------------------------------------------------
# Inference round trip and source
# ---------------------------------------------------------------------------


_NAMES = {
    "entries",
    "ignore",
    "paths",
    "validate",
    "scaffold",
    "source",
    "root",
    "bindings",
}


def from_inferred(
    schema: InferredSchema, name: str = "Inferred", *, hidden: bool = False
) -> type[Tree]:
    """A schema class with one entry per layout of an inferred schema.

    Each entry keeps its layout's kind, pattern and cardinality (the
    layout's observed ``optional`` and ``many``), so the class validates the
    tree it was inferred from. ``hidden`` should match the ``include_hidden``
    the schema was inferred with.
    """
    attrs: dict[str, Any] = {"hidden": hidden}
    for lay in schema.layouts:
        attr = _unique(_slug(lay.expr.pattern), attrs)
        attrs[attr] = Entry(
            lay.expr,
            "dir" if lay.kind == "dir" else "file",
            optional=lay.optional,
            many=lay.many,
        )
    return type(name, (Tree,), attrs)


def _slug(pattern: str) -> str:
    s = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}", r"\1", pattern)
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_").lower()
    if not s or s[0].isdigit():
        s = "p_" + s
    if keyword.iskeyword(s) or s in _NAMES:
        s += "_"
    return s


def _unique(name: str, taken: Mapping[str, Any]) -> str:
    out, i = name, 2
    while out in taken:
        out = f"{name}_{i}"
        i += 1
    return out


def _ident(name: str) -> str:
    return (
        name
        if name.isidentifier() and not keyword.iskeyword(name)
        else f"p_{_slug(name)}"
    )


_KIND_MAKERS = {
    Kind.SEGMENT: "Segment",
    Kind.SUBPATH: "SubPath",
    Kind.PATH: "AnyPath",
    Kind.ABSOLUTE: "Absolute",
}


def _param_source(p: Param) -> tuple[str, set[str]]:
    """Source for ``p`` and the wend names it uses."""
    args = [repr(p.name)]
    maker = _KIND_MAKERS.get(p.kind, "Param")
    if p.type is not None:
        if maker not in ("Param", "Segment"):
            maker = "Param"
            args.append(f"kind=Kind.{p.kind.name}")
        args.append(f"type={p.type.__name__}")
    if p.choices is not None:
        args.append(f"choices={sorted(p.choices, key=repr)!r}")
    if p.has_default:
        args.append(f"default={p.default!r}")
    used = {maker} | ({"Kind"} if "kind=Kind" in "".join(args) else set())
    return f"{maker}({', '.join(args)})", used


def _expr_source(e: PathExpr, var: Mapping[str, str]) -> str:
    """``e`` (relative, without deferred operations) as a str or a T(t"...")."""
    if not e.param_names:
        return repr(e.pattern)
    parts: list[str] = []
    for part in e.parts:
        if isinstance(part, Splice):
            parts.append("{" + var[part.param.name] + "}")
            continue
        text = []
        for piece in part.pieces:
            if isinstance(piece, str):
                text.append(piece.replace("{", "{{").replace("}", "}}"))
            elif isinstance(piece, Field) and isinstance(piece.source, Param):
                conv = f"!{piece.conversion}" if piece.conversion else ""
                spec = piece.static_spec
                if spec is None:
                    raise ValueError(f"{e.pattern!r} has a dynamic format spec")
                spec = f":{spec}" if spec else ""
                text.append("{" + var[piece.source.name] + conv + spec + "}")
            else:
                raise ValueError(f"Cannot write {e.pattern!r} as source")
        parts.append("".join(text))
    body = "/".join(parts).replace("\\", "\\\\").replace('"', '\\"')
    return f'T(t"{body}")'
