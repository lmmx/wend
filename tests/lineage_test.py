"""Lineage and content addressing (wend.lineage; docs/SEMANTICS.md §13)."""

import json
import os
import pickle

import pytest

from wend import Absent, Creatable, Exists, File, Lens, P, Param, Readable, Step, T
from wend.lineage import (
    Ledger,
    content_key,
    digest_file,
    explain,
    tags,
    upstream,
    values_key,
)


root, day = Param("root"), Param("day")


# -- tags and the lineage of expressions --------------------------------------


def test_tags_are_metadata_kept_by_bind_and_rebase():
    raw = (P(root) / "raw" / T(t"{day}.csv")).tag(source="upload", owner="ingest")
    assert raw == P(root) / "raw" / T(t"{day}.csv")
    assert dict(raw.tags) == {"source": "upload", "owner": "ingest"}
    assert dict(raw.bind(root="/d").tags) == dict(raw.tags)
    assert dict(raw.rebase(P("/x")).tags) == dict(raw.tags)
    assert dict(raw.tag(owner="etl").tags)["owner"] == "etl"
    assert not raw.parent.tags and not raw.with_suffix(".csv").tags
    assert dict(raw.requires(Exists).tags) == dict(raw.tags)
    assert dict(pickle.loads(pickle.dumps(raw)).tags) == dict(raw.tags)
    assert "tags={'source': 'upload'" in repr(raw)
    with pytest.raises(TypeError):
        raw.tags["x"] = 1  # read-only


def test_upstream_explain_and_inherited_tags():
    raw = (P(root) / "raw" / T(t"{day}.csv")).tag(source="upload")
    clean = raw.with_suffix(".parquet").tag(stage="clean")
    report = clean.cousin("../reports", T(t"{day}.md"))
    ups = upstream(report)
    assert raw in ups and clean in ups and ups.index(raw) < ups.index(clean)
    text = explain(report)
    assert "with_suffix({root}/raw/{day}.csv, '.parquet')" in text
    assert text.splitlines()[-1].startswith("{root}/reports/{day}.md = cousin(")
    assert tags(report) == {"source": "upload", "stage": "clean"}
    assert explain(P("/a")) == "/a (built directly)"


# -- digests and content keys -------------------------------------------------


def test_content_keys_name_contents(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("1,2\n")
    b.write_text("3,4\n")
    assert digest_file(a).startswith("sha256:")
    k = content_key(a, b)
    assert len(k) == 16 and k == content_key(a, b) != content_key(b, a)
    a.write_text("1,2,3\n")
    assert content_key(a, b) != k
    assert values_key(model="resnet", lr=0.1) == values_key(lr=0.1, model="resnet")
    assert values_key(model="resnet", lr=0.1) != values_key(model="resnet", lr=0.2)


def test_a_content_addressed_layout_round_trips(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("x\n")
    key = Param("key")
    cache = P(root) / "cache" / T(t"{key}") / "features.parquet"
    out = cache.render(root=tmp_path, key=content_key(raw))
    m = cache.match(out)
    assert m is not None and m["key"] == content_key(raw)
    raw.write_text("y\n")
    assert m["key"] != content_key(raw)  # the cached path no longer names raw


# -- the ledger ---------------------------------------------------------------


def test_ledger_records_provenance_and_answers_up_and_down(tmp_path):
    ledger = Ledger(tmp_path / "lineage.jsonl")
    raw, clean, report = (
        tmp_path / n for n in ("raw.csv", "clean.parquet", "report.md")
    )
    raw.write_text("a")
    clean.write_text("b")
    r = ledger.record(clean, [raw], operation="clean", bindings={"day": "mon"})
    assert r.inputs == ((str(raw), digest_file(raw)),) and r.digest == digest_file(
        clean
    )
    report.write_text("c")
    ledger.record(report, [clean], operation="summarise", tags={"stage": "report"})
    assert ledger.provenance(report).operation == "summarise"
    assert ledger.provenance(tmp_path / "nowhere") is None
    assert ledger.upstream(report) == [str(clean), str(raw)]
    assert ledger.downstream(raw) == [str(clean), str(report)]
    assert ledger.stale(clean) == [] and ledger.stale(report) == []
    raw.write_text("changed")
    assert ledger.stale(clean) == [str(raw)]
    raw.unlink()
    assert ledger.stale(clean) == [str(raw)]
    # one JSON object per line
    lines = (tmp_path / "lineage.jsonl").read_text().splitlines()
    assert [json.loads(ln)["operation"] for ln in lines] == ["clean", "summarise"]


def test_the_latest_record_is_the_provenance(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl", digests=False)
    ledger.record(tmp_path / "out", [tmp_path / "a"], operation="v1")
    ledger.record(tmp_path / "out", [tmp_path / "b"], operation="v2")
    assert ledger.provenance(tmp_path / "out").operation == "v2"
    assert ledger.upstream(tmp_path / "out") == [str(tmp_path / "b")]
    assert ledger.downstream(tmp_path / "a") == []


def test_a_step_run_through_a_ledger_records_its_outputs(tmp_path):
    src = (
        (P(root) / "raw" / T(t"{day}.csv"))
        .requires(File, Exists, Readable)
        .tag(source="upload")
    )
    dst = (
        (P(root) / "clean" / T(t"{day}.csv"))
        .requires(Absent, Creatable)
        .ensures(Exists)
    )
    convert = Step(src=src, dst=dst)
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "mon.csv").write_text("a,b\n")
    ledger = Ledger(tmp_path / ".lineage.jsonl")
    with ledger.run(convert, root=tmp_path, day="mon") as p:
        p["dst"].parent.mkdir(parents=True, exist_ok=True)
        p["dst"].write_text(p["src"].read_text().upper())
    rec = ledger.provenance(tmp_path / "clean" / "mon.csv")
    assert rec is not None
    assert [i for i, _ in rec.inputs] == [str(tmp_path / "raw" / "mon.csv")]
    assert rec.bindings == {"root": str(tmp_path), "day": "mon"}
    assert rec.operation.startswith("Step(")
    # a failing body records nothing
    (tmp_path / "raw" / "tue.csv").write_text("c,d\n")
    with pytest.raises(RuntimeError):
        with ledger.run(convert, root=tmp_path, day="tue"):
            raise RuntimeError
    assert len(ledger.records()) == 1


def test_invalidating_dependents_with_a_lens_and_glob(tmp_path):
    """Part 1's cache invalidation: find what was built from a changed input."""
    name = Param("name")
    build = Lens(
        P(tmp_path) / "src" / T(t"{name}.md"), P(tmp_path) / "site" / T(t"{name}.html")
    )
    ledger = Ledger(tmp_path / "lineage.jsonl")
    (tmp_path / "src").mkdir()
    (tmp_path / "site").mkdir()
    for n in ("a", "b"):
        (tmp_path / "src" / f"{n}.md").write_text(n)
    for m in build.source.glob():
        out = build(m.path)
        out.write_text(f"<p>{m['name']}</p>")
        ledger.record(out, [m.path], operation="render")
    (tmp_path / "src" / "a.md").write_text("changed")
    stale = [m.path for m in build.target.glob() if ledger.stale(m.path)]
    assert [os.path.basename(p) for p in stale] == ["a.html"]
    assert ledger.downstream(tmp_path / "src" / "a.md") == [
        str(tmp_path / "site" / "a.html")
    ]
