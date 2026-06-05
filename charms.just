# Centralized justfile for the Canonical Observability charms
set shell := ["bash", "-uc"]

charm_name := `echo ${PWD##*/} | sed 's/-operator$//'`  # Get the charm name from the folder name

export UV_FROZEN := "true"  # Prevent `uv run` from updating the lockfile
export PYTHONPATH := ".:./lib:./src"


[private]
@default:
    just --list

# Print the charm name
[group("info")]
@name:
  echo "{{charm_name}}"


# Update uv.lock dependencies
[group("maintenance")]
lock:
    unset UV_FROZEN; uv lock --upgrade --no-cache

# Scan for security vulnerabilities
[group("maintenance")]
scan:
    @echo "Scanning for security vulnerabilities..."
    uvx uv-secure

# Fetch centralized files from canonical/observability
[group("maintenance")]
refresh:
    #!/usr/bin/env bash
    which -s gh || { echo "gh not found"; exit 1; }
    refresh_folder="blueprints/charms"
    api_path="repos/canonical/observability/contents/$refresh_folder"
    for file in charms.just; do
      echo "Fetching latest '$file' from canonical/observability ..."
      gh api "$api_path/$file" --jq '.content' | base64 --decode > "$file"
      echo "✓ $file updated"
    done


# Format the codebase
[group("dev")]
format: sync
    # Fix generic linting issues
    uv run ruff check --fix-only
    # Fix import-related issues (including ordering)
    uv run ruff check --select=I --fix-only
    # Format the code
    uv run ruff format
    # Format the Terraform modules
    terraform fmt -recursive -check

alias fmt := format

# Lint the codebase
[group("dev")]
lint: sync
    # Lint the code
    uv run ruff check
    # Run static checks
    uv run ty check src
    # Check for misspellings
    uv run codespell src
    # Check for dead code
    uv run vulture src
    # Run actionlint on GitHub Actions workflows
    test -d .github/workflows && uvx --from=actionlint-py actionlint
    @echo "✓ Linting passed!"


# Run all quality checks: formatting, linting and unit tests
[group("dev")]
check: sync format lint unit
    @echo; echo "✓ All checks passed!"

# Sync the virtual environment (.venv)
[private, group("dev")]
sync:
    uv sync --all-groups --all-extras

# Sync and activate the virtual environment (.venv)
[group("dev")]
venv:
    @echo "Activating virtual environment..."
    @uv sync --all-groups --all-extras
    @. .venv/bin/activate; exec "$SHELL" -i


# Run unit tests
[group("test")]
unit *args: sync
    uv run coverage run --source=src -m pytest tests/unit {{ args }}

# Run integration tests
[group("test")]
integration *args: sync
    uv run pytest --exitfirst tests/integration {{ args }}


# Update the Terraform README with auto-generated content
[group("terraform")]
terraform-docs:
    which terraform-docs > /dev/null 2>&1 || { echo "× terraform-docs not found"; exit 1; }
    terraform-docs --config .tfdocs.yaml .
    @echo "✓ Terraform docs updated"

# Lint and validate the Terraform module
[group("terraform")]
terraform-lint:
    which terraform > /dev/null 2>&1 || { echo "× terraform not found"; exit 1; }
    cd terraform && terraform init -backend=false && terraform validate
    terraform fmt -recursive -check
    @echo "✓ Terraform lint passed"


# Release a .charm file to Charmhub
[group("release")]
release charm_file channel:
    #!/usr/bin/env bash
    set -euo pipefail
    # Upload the charm and get the revision
    echo "Uploading charm {{ charm_file }}..."
    upload_output=$(charmcraft upload "{{ charm_file }}" --format=json)
    charm_revision=$(echo "$upload_output" | jq -r '.revision')
    echo "✓ Uploaded charm revision: $charm_revision"
    # Get resources from charmcraft.yaml
    resource_args=""
    if [ -f charmcraft.yaml ]; then
        while IFS= read -r resource_name; do
            upstream=$(yq -r ".resources.\"$resource_name\".\"upstream-source\" // empty" charmcraft.yaml)
            if [ -n "$upstream" ]; then
                echo "Uploading resource '$resource_name' from $upstream..."
                res_output=$(charmcraft upload-resource "{{ charm_name }}" "$resource_name" --image="docker://$upstream" --format=json)
                res_revision=$(echo "$res_output" | jq -r '.revision')
            else
                echo "Fetching latest revision for resource '$resource_name'..."
                res_revision=$(charmcraft resource-revisions "{{ charm_name }}" "$resource_name" --format=json | jq -r '.[0].revision')
            fi
            echo "✓ Resource '$resource_name' revision: $res_revision"
            resource_args="$resource_args --resource=$resource_name:$res_revision"
        done < <(yq -r '.resources | keys | .[]' charmcraft.yaml 2>/dev/null || true)
    fi
    # Release the charm
    echo "Releasing {{ charm_name }} to {{ channel }}..."
    # shellcheck disable=SC2086
    charmcraft release "{{ charm_name }}" --revision="$charm_revision" --channel="{{ channel }}" $resource_args
    echo "✓ Released {{ charm_name }} revision $charm_revision to {{ channel }}"

# Print all commits between the current branch and the merge-base with `ref`
[group("release")]
[arg("ref", help="Branch (or generic ref) from to get the changelog from")]
changelog ref:
    #!/usr/bin/env bash
    set -euo pipefail
    # Sanitize the ref so that either a branch or a commit is valid
    resolved="{{ ref }}"
    if ! git rev-parse --verify "${resolved}" >/dev/null 2>&1; then
        resolved="origin/{{ ref }}"
    fi
    # Find the merge-base 
    base=$(git merge-base HEAD "${resolved}")
    # Parse all commit messages into a "conventional commits" category
    breaking=""
    features=""
    fixes=""
    others=""
    while IFS= read -r msg; do
        if echo "${msg}" | grep -qE '^[a-z]+(\(.+\))?!:'; then
            breaking="${breaking}- ${msg}"$'\n'
        elif echo "${msg}" | grep -qE '^feat(\(.+\))?:'; then
            features="${features}- ${msg}"$'\n'
        elif echo "${msg}" | grep -qE '^fix(\(.+\))?:'; then
            fixes="${fixes}- ${msg}"$'\n'
        else
            others="${others}- ${msg}"$'\n'
        fi
    done < <(git log --format=%s "${base}..HEAD")
    # Print the commits in a Markdown changelog format
    echo "# Changelog"
    echo ""
    if [ -n "${breaking}" ]; then
        echo "## Breaking Changes"
        echo ""
        echo "${breaking}"
    fi
    if [ -n "${features}" ]; then
        echo "## Features"
        echo ""
        echo "${features}"
    fi
    if [ -n "${fixes}" ]; then
        echo "## Fixes"
        echo ""
        echo "${fixes}"
    fi
    if [ -n "${others}" ]; then
        echo "## Others"
        echo ""
        echo "${others}"
    fi


