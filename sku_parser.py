# -*- coding: utf-8 -*-

# Parse filament SKUs from box barcodes.
#
# SKU format: {variant_prefix}-{variant_suffix}-{diameter}-{weight}-SPL
# Example:    B50-K0-1.75-1000-SPL
#
# The material_id is derived by prepending "GF" to the variant prefix:
#   B50 -> GFB50, A00 -> GFA00, etc.

import re


_SKU_RE = re.compile(
    r"^([A-Z]\d{2})"           # variant prefix (e.g. B50)
    r"-([A-Z]\d)"              # variant suffix (e.g. K0)
    r"-(\d+(?:\.\d+)?)"        # diameter (e.g. 1.75)
    r"-(\d+)"                  # weight in grams (e.g. 1000)
    r"-SPL$",                  # spool marker
    re.IGNORECASE,
)


def parse_sku(sku: str) -> dict | None:
    """
    Parse a filament SKU string.

    Returns a dict with the fields that can be derived from the SKU,
    or None if the string doesn't match the expected format.

    Example:
        parse_sku("B50-K0-1.75-1000-SPL")
        -> {
            "material_id": "GFB50",
            "variant_id": "B50-K0",
            "filament_diameter": 1.75,
            "spool_weight": 1000,
            "source": "sku",
        }
    """
    sku = sku.strip().upper()
    m = _SKU_RE.match(sku)
    if not m:
        return None

    prefix = m.group(1)
    suffix = m.group(2)
    diameter = float(m.group(3))
    weight = int(m.group(4))

    return {
        "material_id": f"GF{prefix}",
        "variant_id": f"{prefix}-{suffix}",
        "filament_diameter": diameter,
        "spool_weight": weight,
        "source": "sku",
    }
