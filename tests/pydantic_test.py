"""Pydantic integration (wend.pydantic, the ``wend[pydantic]`` extra)."""

from pathlib import Path, PurePosixPath
from typing import Annotated, Any

import pytest

from wend import (
    Creatable,
    Dir,
    Exists,
    File,
    Match,
    NotInvertibleError,
    P,
    Param,
    SubPath,
    T,
    U,
    Under,
    counter,
)


pydantic = pytest.importorskip("pydantic")
from pydantic import BaseModel, ValidationError  # noqa: E402

from wend.pydantic import PathOf  # noqa: E402


root, name = Param("root"), Param("name")
csv = P(root) / "raw" / T(t"{name}.csv")


def _error(model: type[BaseModel], **data: Any) -> str:
    with pytest.raises(ValidationError) as info:
        model(**data)
    (err,) = info.value.errors()
    return err["type"]


def test_a_path_must_match_and_its_type_decides_the_value():
    class M(BaseModel):
        path: Annotated[Path, PathOf(csv)]
        text: Annotated[str, PathOf(csv)] = "/d/raw/b.csv"
        pure: Annotated[PurePosixPath, PathOf(csv)] = PurePosixPath("/d/raw/c.csv")
        match: Annotated[Match, PathOf(csv)] = None  # type: ignore[assignment]

    m = M(
        path="/d/raw/a.csv",
        text="/d/raw//b.csv",
        pure="/d/raw/c.csv",
        match="/d/raw/a.csv",
    )
    assert m.path == Path("/d/raw/a.csv")
    assert m.text == "/d/raw/b.csv"  # canonical
    assert m.pure == PurePosixPath("/d/raw/c.csv")
    assert m.match == {"root": "/d", "name": "a"} and m.match.path == "/d/raw/a.csv"
    assert m.model_dump_json() == (
        '{"path":"/d/raw/a.csv","text":"/d/raw/b.csv","pure":"/d/raw/c.csv",'
        '"match":"/d/raw/a.csv"}'
    )
    assert _error(M, path="/d/raw/a.parquet") == "wend_no_match"
    assert _error(M, path=3) == "wend_bindings"
    assert _error(M, path=b"/d/raw/a.csv") == "wend_path"


def test_bindings_are_rendered_at_validation_time():
    total = Param("total", type=int, default=10)
    shard = P(root) / counter("chunk", width=3, of_total=True, total=total)

    class Job(BaseModel):
        out: Annotated[Match, PathOf(shard)]

    class Run(BaseModel):
        root: str
        idx: int

    assert Job(out={"root": "/d", "idx": 1}).out.path == "/d/chunk_001-of-010"
    job = Job(out=Run(root="/d", idx=2))  # an object's fields bind by name
    assert job.out == {"root": "/d", "idx": 2, "total": 10}
    assert _error(Job, out={"root": "/d"}) == "wend_render"  # idx is missing
    assert _error(Job, out={"root": "/d", "idx": "x"}) == "wend_render"


def test_preconditions_are_checked(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("x")
    (tmp_path / "raw" / "d.csv").mkdir()
    src = csv.requires(File, Exists)

    class M(BaseModel):
        src: Annotated[Path, PathOf(src)]

    assert M(src=tmp_path / "raw/a.csv").src == tmp_path / "raw/a.csv"
    assert M(src={"root": str(tmp_path), "name": "a"}).src == tmp_path / "raw/a.csv"
    assert _error(M, src=tmp_path / "raw/b.csv") == "wend_condition"
    assert _error(M, src=tmp_path / "raw/d.csv") == "wend_condition"


def test_ambiguity_is_a_validation_error_and_a_bad_declaration_is_not():
    a, b = Param("a"), Param("b")

    class Ambiguous(BaseModel):
        p: Annotated[str, PathOf(T(t"{a}{b}"))]

    assert _error(Ambiguous, p="xy") == "wend_ambiguous"

    class Deferred(BaseModel):
        p: Annotated[str, PathOf((P(root) / SubPath("s")).parent)]

    with pytest.raises(NotInvertibleError):
        Deferred(p="/x/y")


def test_a_union_field_reports_the_alternative():
    logs = U(t"{root}/app.log", t"{root}/app.log.gz")

    class M(BaseModel):
        log: Annotated[Match, PathOf(logs)]

    assert M(log="/v/app.log.gz").log.alternative == 1  # type: ignore[attr-defined]
    assert _error(M, log={"root": "/v"}) == "wend_render"  # two alternatives


def test_conditions_are_validators(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x")

    class M(BaseModel):
        file: Annotated[Path, File, Exists] = f
        dir: Annotated[Path, Dir, Exists] = tmp_path
        new: Annotated[Path, Creatable] = tmp_path / "new"
        inside: Annotated[str, Under(tmp_path)] = str(f)

    M()
    assert _error(M, file=tmp_path) == "wend_condition"
    assert _error(M, file=tmp_path / "nope") == "wend_condition"
    assert _error(M, dir=f) == "wend_condition"
    assert _error(M, new=f / "x") == "wend_condition"
    assert _error(M, inside="/etc/passwd") == "wend_condition"
    assert _error(M, inside=f"{tmp_path}/../x") == "wend_condition"


def test_conditions_combine_with_a_pattern(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.csv").write_text("x")

    class M(BaseModel):
        src: Annotated[Match, PathOf(csv), File, Exists]

    assert M(src=tmp_path / "raw/a.csv").src["name"] == "a"
    assert _error(M, src=tmp_path / "raw/b.csv") == "wend_condition"


def test_an_under_base_with_parameters_needs_a_pattern():
    with pytest.raises(TypeError, match="PathOf"):

        class M(BaseModel):
            p: Annotated[Path, Under(P(root))]


def test_unsupported_field_types_are_refused():
    with pytest.raises(TypeError, match="PathOf"):

        class M(BaseModel):
            p: Annotated[int, PathOf(csv)]


def test_json_schema_names_the_pattern():
    class M(BaseModel):
        src: Annotated[Path, PathOf(csv)]

    prop = M.model_json_schema()["properties"]["src"]
    assert prop["type"] == "string" and prop["format"] == "path"
    assert prop["x-wend-pattern"] == "{root}/raw/{name}.csv"
    assert repr(PathOf(csv)) == "PathOf('{root}/raw/{name}.csv')"
