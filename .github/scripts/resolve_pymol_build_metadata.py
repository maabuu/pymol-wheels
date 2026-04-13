#!/usr/bin/env python3

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from packaging.version import Version


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", default=".", help="Path to the checked out PyMOL repository")
    parser.add_argument("--json-out", required=True, help="Where to write the resolved metadata JSON")
    parser.add_argument("--source-ref", default="", help="The ref requested by the workflow")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    json_out = Path(args.json_out).resolve()

    upstream_version = read_upstream_version(repo_dir)
    parsed_version = Version(upstream_version)

    source_sha = git(repo_dir, "rev-parse", "HEAD")
    source_short_sha = source_sha[:7]
    tags_output = git(repo_dir, "tag", "--points-at", "HEAD")
    tags = [tag for tag in tags_output.splitlines() if tag]
    normalized_tags = {tag.removeprefix("v") for tag in tags}

    is_exact_release = (
        not parsed_version.is_prerelease
        and not parsed_version.is_devrelease
        and upstream_version in normalized_tags
    )

    wheel_version = upstream_version if is_exact_release else f"{upstream_version}+g{source_short_sha}"
    release_version_label = upstream_version if is_exact_release else f"{upstream_version}_{source_short_sha}"

    metadata = {
        "source_ref": args.source_ref,
        "source_sha": source_sha,
        "source_short_sha": source_short_sha,
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
