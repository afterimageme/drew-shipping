#!/usr/bin/env python3
"""Merge new package data from email scan into existing packages.json.

Usage:
    merge_packages.py <existing_packages.json> <new_packages.json> [--output merged.json]

If --output is not specified, writes merged result to <existing_packages.json>.
"""

import argparse
import json
import sys
from pathlib import Path


def normalize_order_number(order_num: str) -> str:
    """Normalize order number for comparison: strip #, trim whitespace, lowercase."""
    if not order_num:
        return ""
    return order_num.strip().lstrip("#").strip().lower()


def merge_packages(existing: list[dict], new_packages: list[dict]) -> list[dict]:
    """Merge new packages into existing list.

    - Match by normalized order number
    - For matches: update tracking, trackingUrl, status, estimatedDelivery
    - For new (no match): add with status "pending" (unless already set)
    """
    # Build lookup of existing packages by normalized order number
    order_index: dict[str, int] = {}
    for i, pkg in enumerate(existing):
        norm = normalize_order_number(pkg.get("orderNumber", ""))
        if norm:
            order_index[norm] = i

    merged = list(existing)  # shallow copy
    added = 0
    updated = 0

    for new_pkg in new_packages:
        new_norm = normalize_order_number(new_pkg.get("orderNumber", ""))

        if new_norm and new_norm in order_index:
            # UPDATE existing package
            idx = order_index[new_norm]
            existing_pkg = merged[idx]
            changed = False

            # Update tracking if new has one and existing doesn't (or is empty)
            new_tracking = new_pkg.get("tracking", "").strip()
            if new_tracking and not existing_pkg.get("tracking", "").strip():
                existing_pkg["tracking"] = new_tracking
                changed = True

            # Update trackingUrl if new has one and existing doesn't
            new_url = new_pkg.get("trackingUrl", "").strip()
            if new_url and not existing_pkg.get("trackingUrl", "").strip():
                existing_pkg["trackingUrl"] = new_url
                changed = True

            # If tracking was added, upgrade status to in-transit
            if new_tracking and existing_pkg.get("status") == "pending":
                existing_pkg["status"] = "in-transit"
                changed = True

            # Update estimatedDelivery if new provides one
            new_delivery = new_pkg.get("estimatedDelivery", "").strip()
            old_delivery = existing_pkg.get("estimatedDelivery", "").strip()
            if new_delivery:
                # Use new delivery date if existing is empty or new is later
                if not old_delivery or new_delivery > old_delivery:
                    existing_pkg["estimatedDelivery"] = new_delivery
                    changed = True

            # Update carrier if existing is "Other" and new has a specific one
            new_carrier = new_pkg.get("carrier", "").strip()
            if (
                new_carrier
                and new_carrier != "Other"
                and existing_pkg.get("carrier") == "Other"
            ):
                existing_pkg["carrier"] = new_carrier
                changed = True

            # Update items if existing has none and new has some
            if new_pkg.get("items") and not existing_pkg.get("items"):
                existing_pkg["items"] = new_pkg["items"]
                changed = True

            # Update name if existing is generic and new is more descriptive
            if new_pkg.get("name") and not existing_pkg.get("name"):
                existing_pkg["name"] = new_pkg["name"]
                changed = True

            if changed:
                updated += 1
                merged[idx] = existing_pkg

        else:
            # ADD new package
            # Ensure required fields
            new_pkg.setdefault("status", "pending")
            new_pkg.setdefault("carrier", "Other")
            new_pkg.setdefault("tracking", "")
            new_pkg.setdefault("trackingUrl", "")
            new_pkg.setdefault("estimatedDelivery", "")
            new_pkg.setdefault("from", "")
            new_pkg.setdefault("items", [])
            new_pkg.setdefault("name", "Unknown Package")
            new_pkg.setdefault("orderNumber", "")
            merged.append(new_pkg)
            added += 1

            # Add to index for dedup within the new batch
            if new_norm:
                order_index[new_norm] = len(merged) - 1

    return merged, added, updated


def main():
    parser = argparse.ArgumentParser(
        description="Merge new package data into existing packages.json"
    )
    parser.add_argument("existing", help="Path to existing packages.json")
    parser.add_argument(
        "new_packages", help="Path to new packages JSON from email scan"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output path (default: overwrite existing file)",
    )
    args = parser.parse_args()

    existing_path = Path(args.existing)
    new_path = Path(args.new_packages)
    output_path = Path(args.output) if args.output else existing_path

    # Load existing
    if existing_path.exists():
        with open(existing_path) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error: invalid JSON in {existing_path}: {e}", file=sys.stderr)
                sys.exit(1)
    else:
        existing = []

    if not isinstance(existing, list):
        print(f"Error: {existing_path} must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    # Load new packages
    if not new_path.exists():
        print(f"Error: {new_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(new_path) as f:
        content = f.read().strip()

    if not content or content == "[]":
        print("No new packages to merge.")
        sys.exit(0)

    try:
        new_packages = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {new_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(new_packages, list):
        print(f"Error: {new_path} must contain a JSON array", file=sys.stderr)
        sys.exit(1)

    # Merge
    merged, added, updated = merge_packages(existing, new_packages)

    # Write output
    with open(output_path, "w") as f:
        json.dump(merged, f, indent=4, ensure_ascii=False)
        f.write("\n")

    print(
        f"Merge complete: {added} added, {updated} updated, {len(merged)} total packages."
    )


if __name__ == "__main__":
    main()
