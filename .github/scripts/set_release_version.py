"""Validate a release tag and make it the version embedded in desktop packages."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


SEMVER_TAG = re.compile(
    r"^v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$"
)


def version_from_tag(tag: str) -> str:
    match = SEMVER_TAG.fullmatch(tag.strip())
    if not match:
        raise ValueError(
            f"Invalid release tag {tag!r}. Expected semantic version format such as v1.9.0."
        )
    return match.group("version")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "tag",
        nargs="?",
        default=os.environ.get("RELEASE_TAG"),
        help="Git tag, for example v1.9.0 (defaults to RELEASE_TAG)",
    )
    parser.add_argument(
        "--version-file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "version.txt",
    )
    args = parser.parse_args()

    if not args.tag:
        parser.error("provide a tag argument or set RELEASE_TAG")
    version = version_from_tag(args.tag)
    args.version_file.write_text(version + "\n", encoding="utf-8")
    print(f"Packaging TODO App version {version} from tag {args.tag}")


if __name__ == "__main__":
    main()
