# Releasing

A release bumps the version in `pyproject.toml`, commits and tags it, publishes the built package to [PyPI](<https://pypi.org/project/wend/>), and makes its GitHub Release. Every step after the first runs in CI.

## Steps

1. **Write the release's notes** under "Unreleased" in [`docs/CHANGELOG.md`](<https://github.com/lmmx/wend/blob/master/docs/CHANGELOG.md>), and any change in behaviour in [`docs/MIGRATING.md`](<https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md>), in a pull request merged before the release.
2. **Run the "Deploy Release" workflow** (`.github/workflows/deploy.yml`) on master, choosing its `bump`: `patch`, `minor`, `major` or `none`. It runs `just release <bump>`, which:
3. bumps the version with `uv version --frozen --bump <bump>`. `--frozen` leaves `uv.lock` as it is, so the lock's own entry for wend can lag the version;
4. titles the changelog's "Unreleased" notes with the new version;
5. commits both as `chore(release): bump 🐍 -> v<version>`;
6. tags the commit with the version;
7. pushes the commit and the tag.

`none` releases the version `pyproject.toml` already has, for a release commit whose tag was never pushed. It makes no commit, and refuses if that version's tag exists or PyPI has it.

A commit or tag pushed with a workflow's token starts no workflow, so Deploy Release then starts the tests and CI on the new tag itself (`gh workflow run ... --ref    <version>`). 3. **CI publishes it** (`.github/workflows/CI.yml`). It builds the wheel and the sdist, generates artifact attestations, and publishes to PyPI with [Trusted Publishing](<https://docs.pypi.org/trusted-publishers/>), so no token is stored in the repository. Only a run on a tag publishes: CI started on a branch builds and attests, and stops there. 4. **The GitHub Release follows** (`.github/workflows/github-release.yml`), which CI calls once the package is published. On the existing tag, once PyPI has the version and the tagged commit's tests have passed, it makes the GitHub Release. Its notes are the version's section of the changelog, then the pull requests since the last release, as GitHub lists them. A tag that has a GitHub Release keeps it as it is, so a re-run makes no second release.

Deploy Release can be started from the repository's Actions tab, with `gh workflow run deploy.yml --ref master -f bump=minor`, or through the GitHub API. The API is how an agent session, such as a Claude Code cloud session, makes a release: it may push branches but not tags, nor make releases, and the workflows do both.

`just release <bump>` also runs locally on master. It pushes from your machine, and a tag pushed from your machine starts CI, which publishes and makes the GitHub Release. `just release --help` shows the options of `uv version --bump`.

## A tag with no GitHub Release

If the GitHub Release was not made (say the tag's tests were cancelled), run the "GitHub Release" workflow on master with the tag. Its `dry_run`, on by default, checks the tag, PyPI and the tests and shows the notes in the run's summary, and makes nothing; run it again with `dry_run` off to make the release. It publishes nothing to PyPI. When the tests did not pass, start them on the tag first (`gh workflow run test.yml --ref <version>`).

## After a release

- The documentation site is published from master on every push, so it already describes the released code.
