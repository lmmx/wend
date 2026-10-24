---
description: "How a wend release is made: the Deploy Release workflow bumps the version, tags it and starts CI on the tag, and CI publishes the package to PyPI with Trusted Publishing."
---

# Releasing

A release bumps the version in `pyproject.toml`, commits and tags it, and publishes the
built package to [PyPI](https://pypi.org/project/wend/).

## Steps

1. **Run the "Deploy Release" workflow** (`.github/workflows/deploy.yml`) on master,
   choosing its `bump`: `patch`, `minor`, `major` or `none`. It runs
   `just release <bump>`, which:
   - bumps the version with `uv version --frozen --bump <bump>`. `--frozen` leaves
     `uv.lock` as it is, so the lock's own entry for wend can lag the version;
   - commits it as `chore(release): bump 🐍 -> v<version>`;
   - tags the commit with the version;
   - pushes the commit and the tag.

   `none` releases the version `pyproject.toml` already has, for a release commit whose
   tag was never pushed. It makes no commit, and refuses if that version's tag exists or
   PyPI has it.
2. **CI publishes it** (`.github/workflows/CI.yml`). A tag pushed with a workflow's token
   starts no workflow, so Deploy Release starts CI on the new tag itself
   (`gh workflow run CI.yml --ref <version>`). CI builds the wheel and the sdist,
   generates artifact attestations, and publishes to PyPI with
   [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so no token is
   stored in the repository. Only a run on a tag publishes: CI started on a branch builds
   and attests, and stops there.

Deploy Release can be started from the repository's Actions tab, with
`gh workflow run deploy.yml --ref master -f bump=minor`, or through the GitHub API. The
API is how an agent session, such as a Claude Code cloud session, makes a release: it
may push branches but not tags, and the workflow pushes the tag itself.

`just release <bump>` also runs locally on master. It pushes from your machine, and a tag
pushed from your machine starts CI, which publishes. `just release --help` shows the
options of `uv version --bump`.

## After a release

- The documentation site is published from master on every push, so it already describes
  the released code.
- Add the release's changes to [`docs/MIGRATING.md`](https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md)
  where they change behaviour.
