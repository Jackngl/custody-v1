#!/usr/bin/env python3
"""Update the integration version inside manifest.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "custom_components" / "custody_schedule" / "manifest.json"


def increment_version(version: str) -> str:
    """Increment the patch version (1.0.x + 1)."""
    # Match version pattern like "1.0.5"
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not match:
        raise ValueError(f"Invalid version format: {version}. Expected format: X.Y.Z")
    
    major, minor, patch = map(int, match.groups())
    new_patch = patch + 1
    return f"{major}.{minor}.{new_patch}"


def get_current_version() -> str:
    """Read the current version from manifest.json."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"manifest not found at {MANIFEST_PATH}")

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise RuntimeError(f"Failed to load manifest: {err}") from err

    version = manifest.get("version")
    if not version:
        raise ValueError("Version field not found in manifest")
    
    return version


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
    if len(sys.argv) == 1:
        # Auto-increment mode
        try:
            current_version = get_current_version()
            new_version = increment_version(current_version)
            update_version(new_version)
        except (FileNotFoundError, ValueError, RuntimeError) as err:
            print(f"Error: {err}")
            sys.exit(1)
    elif len(sys.argv) == 2:
        # Manual version mode
        update_version(sys.argv[1])
    else:
        print("Usage:")
        print("  python scripts/update_version.py          # Auto-increment version (1.0.x + 1)")
        print("  python scripts/update_version.py <version>  # Set specific version")
        sys.exit(1)
