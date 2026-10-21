# Releasing

A release bumps the version in `pyproject.toml`, commits and tags it, and publishes the built package to [PyPI](<https://pypi.org/project/wend/>).

## Steps

1. **Run the "Deploy Release" workflow** (`.github/workflows/deploy.yml`) from the repository's Actions tab. It runs `just release` on master, which:
2. bumps the patch version with `uv version --bump patch`;
3. commits it as `chore(release): bump 🐍 -> v<version>`;
4. tags the commit with the version;
5. pushes the commit and the tag.
6. **CI publishes it** (`.github/workflows/CI.yml`). It builds the wheel and the sdist, generates artifact attestations, and publishes to PyPI with [Trusted Publishing](<https://docs.pypi.org/trusted-publishers/>), so no token is stored in the repository. A tag pushed by a workflow starts no other workflow, so `CI.yml` runs when "Deploy Release" completes, or when a tag is pushed from a person's machine.

For a minor or major release, run `just release minor` (or `major`) locally on master instead. It does the same steps and pushes from your machine. `just release --help` shows the options of `uv version --bump`.

## After a release

- The documentation site is published from master on every push, so it already describes the released code.
- Before the first release after 0.1.1, remove the "Until the next release" note from [Installation](<https://lmmx.github.io/wend/pr-preview/pr-98/getting-started/installation/index.md>) and the home page, which tell readers to install from GitHub.
- Add the release's changes to [`docs/MIGRATING.md`](<https://github.com/lmmx/wend/blob/master/docs/MIGRATING.md>) where they change behaviour.
