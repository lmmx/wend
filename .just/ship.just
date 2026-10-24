# Release a new version, pass --help for options to `uv version --bump`. bump_level none
# releases the version pyproject.toml has, if no tag and no PyPI release has it yet
release bump_level="patch":
    #!/usr/bin/env -S echo-comment --shell-flags="-e" --color bright-green

    ## Exit early if help was requested
    if [[ "{{ bump_level }}" == "--help" ]]; then
        uv version --help
        exit 0
    fi

    if [[ "{{ bump_level }}" == "none" ]]; then
        new_version=$(uv version --short)
        # 🔍 Releasing $new_version as pyproject.toml has it, with no release commit
        if git ls-remote --exit-code --tags origin "refs/tags/$new_version" > /dev/null; then
            # ❌ The tag $new_version already exists
            exit 1
        fi
        if curl -sfo /dev/null "https://pypi.org/pypi/wend/$new_version/json"; then
            # ❌ PyPI already has wend $new_version
            exit 1
        fi
    else
        # 📈 Bump the version in pyproject.toml (patch/minor/major: {{ bump_level }})
        uv version --frozen --bump {{ bump_level }}

        # 📦 Stage all changes (including the version bump)
        git add --all

        # 🔄 Create a temporary commit to capture the new version
        git commit -m "chore(temp): version check"

        # ✂️  Extract the new version number that was just set, undo the commit
        new_version=$(uv version --short)
        git reset --soft HEAD~1

        # 📝 Title the changelog's Unreleased notes $new_version (its GitHub Release takes them)
        python3 docs/scripts/changelog.py release "$new_version"

        # ✅ Stage everything again and create the real release commit
        git add --all
        git commit -m  "chore(release): bump 🐍 -> v$new_version"
    fi

    # 🏷️ Create the git tag for this release
    git tag -a "$new_version" -m "Release $new_version"

    branch_name=$(git rev-parse --abbrev-ref HEAD);
    # 🚀 Push the release commit to $branch_name
    git push origin $branch_name

    # 🚀 Push the commit tag to the remote. Pushed from a person's machine, it starts CI,
    # which publishes to PyPI with Trusted Publishing; Deploy Release starts CI itself
    git push origin "$new_version"
