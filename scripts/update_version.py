#!/usr/bin/env python3
"""Update the integration version inside manifest.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "custom_components" / "custody_schedule" / "manifest.json"


def update_version(version: str) -> None:
    """Replace the manifest version field with the provided value."""
    if not MANIFEST_PATH.exists():
        print(f"manifest not found at {MANIFEST_PATH}")
        sys.exit(1)

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"Failed to load manifest: {err}")
        sys.exit(1)

    old_version = manifest.get("version", "unknown")
    manifest["version"] = version

    try:
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as err:
        print(f"Failed to write manifest: {err}")
        sys.exit(1)

    print(f"Version updated from {old_version} to {version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/update_version.py <version>")
        sys.exit(1)

    update_version(sys.argv[1])
