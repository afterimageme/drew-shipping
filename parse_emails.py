#!/usr/bin/env python3
"""Parse shipping/tracking emails to extract package information."""

import re
from datetime import datetime, timedelta
from typing import Optional

# Tracking number patterns by carrier
TRACKING_PATTERNS = {
    "UPS": re.compile(r"\b1Z[A-Z0-9]{16}\b"),
    "FedEx": re.compile(r"\b\d{12,22}\b"),
    "USPS": re.compile(r"\b(94|93|92|95)\d{18,22}\b"),
    "Amazon": re.compile(r"\bTBA\d{12,}\b"),
    "DHL": re.compile(r"\b\d{10}\b|\b[A-Z]{2}\d{9}[A-Z]{2}\b"),
}

# Order of matching matters: more specific patterns first
CARRIER_MATCH_ORDER = ["UPS", "USPS", "Amazon", "FedEx", "DHL"]

# Carrier detection from sender/subject keywords
CARRIER_KEYWORDS = {
    "UPS": ["ups.com", "ups", "united parcel"],
    "FedEx": ["fedex.com", "fedex", "federal express"],
    "USPS": ["usps.com", "usps", "united states postal"],
    "Amazon": ["amazon.com", "amazon"],
    "DHL": ["dhl.com", "dhl"],
}

# Tracking URL templates
TRACKING_URLS = {
    "UPS": "https://www.ups.com/track?tracknum={tracking}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={tracking}",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking}",
    "Amazon": "https://www.amazon.com/gp/your-account/order-history",
    "DHL": "https://www.dhl.com/us-en/home/tracking.html?tracking-id={tracking}",
}

# Date extraction patterns
DATE_PATTERNS = [
    # "March 19, 2026" or "March 19"
    re.compile(
        r"(?:estimated delivery|arriving|expected by|delivery date|deliver by|"
        r"scheduled delivery)[:\s]*"
        r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s*)?"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
        r"\s+\d{1,2}(?:,?\s*\d{4})?)",
        re.IGNORECASE,
    ),
    # "03/19/2026" or "3/19/2026"
    re.compile(
        r"(?:estimated delivery|arriving|expected by|delivery date|deliver by|"
        r"scheduled delivery)[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
        re.IGNORECASE,
    ),
    # "2026-03-19"
    re.compile(
        r"(?:estimated delivery|arriving|expected by|delivery date|deliver by|"
        r"scheduled delivery)[:\s]*(\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
]

# Item extraction patterns
ITEM_PATTERNS = [
    # "Shipped: ITEM" or "Your order of ITEM"
    re.compile(
        r"(?:shipped|your order of|order contains)[:\s]+(.+?)(?:\n|$)", re.IGNORECASE
    ),
    # Amazon "Items Ordered" section - grab lines after it
    re.compile(
        r"Items Ordered[:\s]*\n(.+?)(?:\n\n|\nOrder)", re.IGNORECASE | re.DOTALL
    ),
]


def _detect_carrier_from_context(subject: str, from_addr: str) -> Optional[str]:
    """Detect carrier from email sender or subject keywords."""
    text = f"{subject} {from_addr}".lower()
    for carrier, keywords in CARRIER_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return carrier
    return None


def _extract_tracking(
    text: str, hint_carrier: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Extract tracking number and carrier from text.

    Returns (tracking_number, carrier) or (None, None).
    """
    # If we have a carrier hint, try that pattern first
    if hint_carrier and hint_carrier in TRACKING_PATTERNS:
        match = TRACKING_PATTERNS[hint_carrier].search(text)
        if match:
            return match.group(0), hint_carrier

    # Try patterns in specificity order
    for carrier in CARRIER_MATCH_ORDER:
        pattern = TRACKING_PATTERNS[carrier]
        match = pattern.search(text)
        if match:
            tracking = match.group(0)
            # FedEx and DHL patterns are loose (just digits), skip short
            # digit-only matches that are likely not tracking numbers
            if carrier == "DHL" and len(tracking) == 10:
                # Could be a phone number or other 10-digit number; only
                # use if we have DHL context
                if hint_carrier != "DHL":
                    continue
            return tracking, carrier

    return None, None


def _extract_date(text: str) -> Optional[str]:
    """Extract estimated delivery date from text, return as YYYY-MM-DD."""
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            date_str = match.group(1).strip()
            return _parse_date_string(date_str)
    return None


def _parse_date_string(date_str: str) -> Optional[str]:
    """Parse various date string formats to YYYY-MM-DD."""
    # Try ISO format first
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]

    # Try MM/DD/YYYY
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", date_str)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"

    # Try "March 19, 2026" or "Mar 19"
    formats = [
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
        "%B %d",
        "%b %d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip().rstrip(","), fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def _extract_items(subject: str, body: str) -> list[str]:
    """Extract item names from email content."""
    items = []

    # Try body patterns
    for pattern in ITEM_PATTERNS:
        match = pattern.search(body)
        if match:
            raw = match.group(1).strip()
            # Split on newlines for multi-item sections
            for line in raw.split("\n"):
                line = line.strip()
                if line and len(line) > 3 and len(line) < 200:
                    # Skip lines that look like metadata
                    if not re.match(
                        r"^(qty|quantity|price|total|\$|#)", line, re.IGNORECASE
                    ):
                        items.append(line)

    # If nothing from body, try subject line
    if not items:
        # "Shipped: Your Widget Pro" / "Your order: Widget"
        m = re.search(
            r"(?:shipped|your order)[:\s-]+(.+?)(?:\s*-\s*|$)", subject, re.IGNORECASE
        )
        if m:
            item = m.group(1).strip()
            if item and len(item) > 2:
                items.append(item)

    return items


def _generate_tracking_url(carrier: str, tracking: str) -> str:
    """Generate a tracking URL for the given carrier and tracking number."""
    template = TRACKING_URLS.get(carrier, "")
    if template:
        return template.format(tracking=tracking)
    return ""


def _generate_package_name(carrier: str, from_addr: str, items: list[str]) -> str:
    """Generate a human-readable package name."""
    # Try to get sender name from from_addr
    sender = ""
    if "<" in from_addr:
        sender = from_addr.split("<")[0].strip().strip('"')
    if not sender:
        # Extract domain
        m = re.search(r"@([\w.-]+)", from_addr)
        if m:
            domain = m.group(1)
            sender = domain.split(".")[0].title()

    if items:
        item_preview = items[0]
        if len(item_preview) > 40:
            item_preview = item_preview[:37] + "..."
        if sender:
            return f"{sender} - {item_preview}"
        return item_preview

    if sender:
        return f"{sender} - Package"
    return f"{carrier} Package"


def parse_shipping_email(subject: str, body: str, from_addr: str) -> Optional[dict]:
    """Parse a shipping/tracking email and extract package information.

    Args:
        subject: Email subject line.
        body: Email body text (plain text preferred).
        from_addr: Sender email address.

    Returns:
        A package dict matching the dashboard schema, or None if no
        tracking number was found.
    """
    full_text = f"{subject}\n{body}"

    # Detect carrier from context
    hint_carrier = _detect_carrier_from_context(subject, from_addr)

    # Extract tracking number
    tracking, carrier = _extract_tracking(full_text, hint_carrier)
    if not tracking:
        return None

    # Use context carrier if tracking pattern didn't determine one
    if not carrier and hint_carrier:
        carrier = hint_carrier
    if not carrier:
        carrier = "Other"

    # Extract other fields
    items = _extract_items(subject, body)
    estimated_delivery = _extract_date(full_text)
    tracking_url = _generate_tracking_url(carrier, tracking)
    name = _generate_package_name(carrier, from_addr, items)

    return {
        "name": name,
        "carrier": carrier,
        "tracking": tracking,
        "trackingUrl": tracking_url,
        "status": "in-transit",
        "estimatedDelivery": estimated_delivery or "",
        "from": from_addr,
        "items": items,
    }


if __name__ == "__main__":
    # Quick test
    result = parse_shipping_email(
        subject="Your Amazon.com order has shipped",
        body="Items Ordered\nOXO Good Grips Utensil Set\n\nTracking: TBA934857201000\nEstimated delivery: March 19, 2026",
        from_addr="shipment-tracking@amazon.com",
    )
    if result:
        import json

        print(json.dumps(result, indent=2))
    else:
        print("No tracking found")
