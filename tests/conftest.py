"""What a test needs, and what did not run.

Two markers:

- ``linux``: Linux system calls (``openat2``, ``renameat2``, ``O_TMPFILE``,
  leases, inotify, memfd seals). Skipped on other platforms.
- ``privileged``: root or a capability: mounts, loop devices,
  ``CAP_LINUX_IMMUTABLE``, acting as other users. Such a test skips without
  it, and the summary lists every privileged test that did not run, so that
  the evidence a journal cites is never absent without saying so. With
  ``WEND_REQUIRE_PRIVILEGED=1`` (the privileged CI job), a privileged test
  that skips fails instead.

Measurements made by scripts (benchmarks, probes, the mutation harness) are
not tests and run in neither job; docs/journal/2026-10-22-research-index.md
lists them with the commands that rerun them.
"""

import os
import sys

import pytest


REQUIRE = "WEND_REQUIRE_PRIVILEGED"
_skipped: dict[str, str] = {}
_ran: set[str] = set()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "linux: needs Linux system calls")
    config.addinivalue_line(
        "markers", "privileged: needs root or a capability; listed when it skips"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if sys.platform.startswith("linux"):
        return
    skip = pytest.mark.skip(reason="needs Linux system calls")
    for item in items:
        if item.get_closest_marker("linux"):
            item.add_marker(skip)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    if item.get_closest_marker("privileged") is None:
        return report
    if report.when == "call" and not report.skipped:
        _ran.add(item.nodeid)
    if report.skipped:
        reason = (
            report.longrepr[2]
            if isinstance(report.longrepr, tuple)
            else str(report.longrepr)
        )
        if os.environ.get(REQUIRE) == "1":
            report.outcome = "failed"
            report.longrepr = f"a privileged test skipped where {REQUIRE}=1: {reason}"
        else:
            _skipped[item.nodeid] = reason
    return report


def pytest_terminal_summary(terminalreporter) -> None:
    tr = terminalreporter
    if not (_skipped or _ran):
        return
    tr.section("privileged evidence")
    for nodeid, reason in sorted(_skipped.items()):
        tr.write_line(f"NOT RUN  {nodeid}: {reason}")
    tr.write_line(
        f"{len(_ran)} privileged tests ran; {len(_skipped)} did not"
        + (
            " (their claims are unchecked by this run: run as root, or see the "
            "privileged CI job)"
            if _skipped
            else ""
        )
    )
