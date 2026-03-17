#!/usr/bin/env python3
"""Sync packages.json data into index.html for the Drew's Move dashboard."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
INDEX_HTML = SCRIPT_DIR / "index.html"
PACKAGES_JSON = SCRIPT_DIR / "packages.json"

# Regex to match the PACKAGES constant block in index.html
# Greedy match up to the last ]; before LAST_UPDATED
PACKAGES_RE = re.compile(
    r"const PACKAGES = \[.*\n\];",
    re.DOTALL,
)

# Regex to match the LAST_UPDATED constant
LAST_UPDATED_RE = re.compile(
    r'(const LAST_UPDATED = ")[^"]*(";\s*)',
)


def load_packages(path: Path) -> list[dict]:
    """Load and validate packages from JSON file."""
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"Error: {path} must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    required_keys = {"name", "carrier", "tracking", "status"}
    for i, pkg in enumerate(data):
        missing = required_keys - set(pkg.keys())
        if missing:
            print(
                f"Warning: package {i} missing keys: {missing}",
                file=sys.stderr,
            )
        # Ensure all expected keys exist with defaults
        pkg.setdefault("trackingUrl", "")
        pkg.setdefault("estimatedDelivery", "")
        pkg.setdefault("from", "")
        pkg.setdefault("items", [])

    return data


def format_packages_js(packages: list[dict]) -> str:
    """Format packages list as a JavaScript constant assignment."""
    # Use json.dumps for proper escaping, then adjust formatting
    js_array = json.dumps(packages, indent=4, ensure_ascii=False)
    return f"const PACKAGES = {js_array};"


def update_html(html: str, packages: list[dict], timestamp: str) -> str:
    """Replace PACKAGES and LAST_UPDATED in the HTML string."""
    new_packages_js = format_packages_js(packages)

    # Replace PACKAGES block
    updated = PACKAGES_RE.sub(new_packages_js, html)
    if updated == html:
        print("Warning: could not find PACKAGES block in index.html", file=sys.stderr)

    # Replace LAST_UPDATED
    before = updated
    updated = LAST_UPDATED_RE.sub(rf"\g<1>{timestamp}\2", updated)
    if updated == before:
        print("Warning: could not find LAST_UPDATED in index.html", file=sys.stderr)

    return updated


def main():
    parser = argparse.ArgumentParser(description="Sync packages.json into index.html")
    parser.add_argument(
        "packages_file",
        nargs="?",
        default=str(PACKAGES_JSON),
        help="Path to packages JSON file (default: packages.json in script dir)",
    )
    parser.add_argument(
        "--html",
        default=str(INDEX_HTML),
        help="Path to index.html (default: index.html in script dir)",
    )
    parser.add_argument(
        "--remove-samples",
        action="store_true",
        default=False,
        help="Remove sample data, only use packages from JSON. "
        "Auto-enabled when packages.json has entries.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print updated HTML to stdout instead of writing to file.",
    )
    args = parser.parse_args()

    packages_path = Path(args.packages_file)
    html_path = Path(args.html)

    # Load packages from JSON
    packages = load_packages(packages_path)

    # Auto-enable --remove-samples if we have real data
    if packages:
        args.remove_samples = True

    # Read current HTML
    if not html_path.exists():
        print(f"Error: {html_path} not found", file=sys.stderr)
        sys.exit(1)

    html = html_path.read_text()

    # If not removing samples and no packages, keep existing HTML
    if not packages and not args.remove_samples:
        print("No packages in JSON and --remove-samples not set. Nothing to do.")
        return

    # Generate timestamp
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Update HTML
    updated_html = update_html(html, packages, timestamp)

    if args.dry_run:
        print(updated_html)
    else:
        html_path.write_text(updated_html)
        print(f"Updated {html_path} with {len(packages)} packages at {timestamp}")


if __name__ == "__main__":
    main()
