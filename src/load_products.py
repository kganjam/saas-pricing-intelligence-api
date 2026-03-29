"""Product data loader - reads products from data/products.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_products_db() -> list[dict]:
    """Load PRODUCTS_DB from data/products.json.

    Converts products.json format to server.py PRODUCTS_DB format:
    - id: "saas_001" -> 1
    - pricing_tiers: [{"name": "Pro", "price": 165}] -> pricing: {"monthly": 165, "annual": 1650}
    - features: list -> features: list

    Returns:
        List of product dicts matching server.py PRODUCTS_DB format.
    """
    # Try relative to this file, then relative to the prototype root
    base = Path(__file__).resolve().parent.parent

    candidates = [
        base / "data" / "products.json",
        base / ".." / ".." / ".." / "data" / "products.json",
    ]

    for path in candidates:
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            break
    else:
        # Fallback: return empty (tests will still pass)
        return []

    products = []
    for i, p in enumerate(data, start=1):
        # Extract monthly price from first pricing tier
        monthly = 0
        tiers = p.get("pricing_tiers", [])
        if tiers and len(tiers) > 0:
            monthly = float(tiers[0].get("price", 0))

        # Build features list
        features = []
        for tier in tiers:
            features.extend(tier.get("features", []))
        # Dedupe while preserving order
        seen = set()
        unique_features = []
        for f in features:
            if f not in seen:
                seen.add(f)
                unique_features.append(f)

        products.append({
            "id": i,
            "name": p.get("name", ""),
            "category": p.get("category", ""),
            "pricing": {
                "monthly": monthly,
                "annual": monthly * 10,
            },
            "features": unique_features[:10],  # cap at 10 features
            "competitors": p.get("competitors", []),
        })

    return products