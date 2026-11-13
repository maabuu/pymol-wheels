#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def git(repo_dir: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_dir,
        text=True,
    ).strip()


def read_upstream_version(repo_dir: Path) -> str:
    version_header = repo_dir / "layer0" / "Version.h"
    content = version_header.read_text(encoding="utf-8")
    match = re.search(r'_PyMOL_VERSION\s+"([^"]+)"', content)
    if not match:
        raise ValueError(f"Could not find _PyMOL_VERSION in {version_header}")
    return match.group(1)


def is_prerelease_version(version: str) -> bool:
    return bool(re.search(r"(a|b|rc|dev)\d*$", version, flags=re.IGNORECASE))


def normalize_version(version: str) -> str:
    """Return upstream's version in normalized PEP 440 form, e.g. '3.2.0a' -> '3.2.0a0'."""
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:(a|b|rc)(\d*))?", version.strip(), flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Unsupported upstream version format: {version!r}")
    release, phase, number = match.groups()
    release = ".".join(str(int(part)) for part in release.split("."))
    if phase is None:
        return release
    return f"{release}{phase.lower()}{int(number or 0)}"


def supports_json_build_option(repo_dir: Path) -> bool:
    # build.yml passes `--config-settings json=True` (glTF/GLB export through
    # nlohmann-json). Upstream added that option after v3.1.0; older sources
    # reject it and need a different recipe (collada2gltf, numpy<2).
    setup_py = (repo_dir / "setup.py").read_text(encoding="utf-8")
    return bool(re.search(r"""["']--json["']""", setup_py))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", default=".", help="Path to the checked out PyMOL repository")
    parser.add_argument("--json-out", required=True, help="Where to write the resolved metadata JSON")
    parser.add_argument("--source-ref", default="", help="The ref requested by the workflow")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    json_out = Path(args.json_out).resolve()

    upstream_version = read_upstream_version(repo_dir)
    if not supports_json_build_option(repo_dir):
        print(
            f"::error::PyMOL {upstream_version} (ref '{args.source_ref}') predates the `json` "
            "build option this workflow relies on. Only sources newer than v3.1.0 are supported."
        )
        sys.exit(1)
    if git(repo_dir, "rev-parse", "--is-shallow-repository") == "true":
        print("::error::The PyMOL checkout is shallow; the full history is needed to number the build.")
        sys.exit(1)

    source_sha = git(repo_dir, "rev-parse", "HEAD")
    source_short_sha = source_sha[:7]
    commit_count = int(git(repo_dir, "rev-list", "--count", "HEAD"))
    tags_output = git(repo_dir, "tag", "--points-at", "HEAD")
    tags = [tag for tag in tags_output.splitlines() if tag]
    normalized_tags = {tag.removeprefix("v") for tag in tags}

    is_exact_release = (
        not is_prerelease_version(upstream_version)
        and upstream_version in normalized_tags
    )

    # Upstream rarely bumps its version, so every development build gets its own
    # public version: upstream's version plus `.post<number of commits>`. Along
    # upstream's history this is unique and increases with every commit, and
    # (unlike a `+g<sha>` local version) it is accepted by PyPI. Exact releases
    # keep upstream's version unchanged.
    base_version = normalize_version(upstream_version)
    wheel_version = base_version if is_exact_release else f"{base_version}.post{commit_count}"
    release_version_label = upstream_version if is_exact_release else f"{upstream_version}_{source_short_sha}"

    metadata = {
        "source_ref": args.source_ref,
        "source_sha": source_sha,
        "source_short_sha": source_short_sha,
        "commit_count": commit_count,
        "upstream_version": upstream_version,
        "wheel_version": wheel_version,
        "release_version_label": release_version_label,
        "is_exact_release": is_exact_release,
        "tags_at_head": tags,
    }

    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            for key, value in metadata.items():
                if isinstance(value, bool):
                    value = str(value).lower()
                elif isinstance(value, list):
                    value = json.dumps(value)
                fh.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
