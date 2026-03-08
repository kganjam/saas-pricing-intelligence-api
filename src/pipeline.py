"""Core runtime pipeline for SaaS Pricing Intelligence API."""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app import PricingIntelligenceEngine, PricingRequest


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def compute_priority_score(request: dict[str, Any], settings: dict[str, Any]) -> float:
    """Prioritize analysis requests by business value."""
    segment = str(request.get("customer_segment", "smb"))
    feature_count = int(request.get("feature_count", 3))

    # Segment factor: enterprise has higher value
    segment_factors = {
        "enterprise": 1.0,
        "mid-market": 0.8,
        "smb": 0.5,
        "startup": 0.3,
    }
    segment_factor = segment_factors.get(segment, 0.5)

    # Feature factor: more features = more valuable analysis
    feature_factor = min(feature_count / 10.0, 1.0)

    score = (0.6 * segment_factor) + (0.4 * feature_factor)
    return round(max(0.0, min(score, 1.0)), 4)


def estimate_conversion_probability(request: dict[str, Any], settings: dict[str, Any]) -> float:
    """Estimate probability of this analysis leading to subscription."""
    segment = str(request.get("customer_segment", "smb"))

    # Base conversion rates by segment
    base_rates = settings.get("base_conversion_rate_by_segment", {})
    base = float(base_rates.get(segment, 0.15))

    probability = base
    return round(max(0.05, min(probability, 0.4)), 4)


def run_pipeline(context: dict[str, Any], clients: dict[str, Any]) -> dict[str, Any]:
    """Execute the SaaS pricing intelligence automation pipeline."""
    del clients

    prototype_root = Path(context["prototype_root"])
    settings_path = prototype_root / "config" / "settings.json"
    sample_path = prototype_root / "config" / "sample_requests.json"

    settings = _load_json(settings_path)

    # Load sample requests
    if sample_path.exists():
        sample_data = _load_json(sample_path)
    else:
        sample_data = _generate_sample_requests(settings)

    max_requests = int(context.get("max_requests") or settings.get("max_requests_per_run", 20))
    selected = score_requests(requests=sample_data, max_requests=max_requests, settings=settings)

    engine = PricingIntelligenceEngine()
    total_analyses = 0
    total_revenue = 0
    per_request_results: list[dict[str, Any]] = []

    for req in selected:
        request = PricingRequest(
            product_name=req.get("product_name", "Sample Product"),
            current_price=float(req.get("current_price", 99.0)),
            competitors=req.get("competitors", ["competitor_a"]),
            customer_segment=req.get("customer_segment", "smb"),
            features=req.get("features", ["api_access", "analytics"]),
            mrr_target=req.get("mrr_target"),
        )

        recommendation = engine.analyze(request)
        probability = estimate_conversion_probability(req, settings)

        # Revenue based on tier subscription value
        tier = req.get("tier", "starter")
        tier_values = settings.get("tier_monthly_values", {})
        tier_value = float(tier_values.get(tier, 49.0))

        expected_revenue = tier_value * probability / 30.0  # Daily expected revenue

        total_analyses += 1
        total_revenue += expected_revenue

        per_request_results.append({
            "product_name": request.product_name,
            "recommended_price": recommendation.recommended_price,
            "confidence": recommendation.confidence,
            "tier": tier,
            "segment": request.customer_segment,
            "conversion_probability": probability,
            "expected_revenue": round(expected_revenue, 4),
        })

    # Cost estimation
    cost_per_analysis = float(settings.get("cost_per_analysis", 0.005))
    cost_estimate = round(total_analyses * cost_per_analysis, 4)

    projected_monthly_revenue = round(total_revenue * 30.0, 2)
    dry_run = bool(context.get("dry_run", False))

    realized_revenue = 0.0 if dry_run else round(total_revenue, 4)
    realized_cost = 0.0 if dry_run else cost_estimate

    run_artifact = {
        "idea_id": context["idea_id"],
        "timestamp": context["run_started"],
        "analyses_generated": total_analyses,
        "projected_monthly_revenue": projected_monthly_revenue,
        "results": per_request_results,
        "dry_run": dry_run,
    }
    artifact_path = prototype_root / "runs" / f"run-{_utc_now_compact()}.json"
    _write_json(artifact_path, run_artifact)

    return {
        "idea_id": context["idea_id"],
        "timestamp": context["run_started"],
        "success": True,
        "revenue": realized_revenue,
        "cost": realized_cost,
        "projected_monthly_revenue": projected_monthly_revenue,
        "analyses_generated": total_analyses,
        "artifact": str(artifact_path.relative_to(prototype_root)),
        "notes": f"Generated pricing analyses for {total_analyses} requests",
    }


def _generate_sample_requests(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate sample pricing analysis requests for testing."""
    products = [
        "Project Management Tool",
        "CRM Software",
        "Marketing Automation",
        "Help Desk System",
        "Accounting Software",
    ]
    segments = ["startup", "smb", "mid-market", "enterprise"]
    features = [
        ["api_access", "analytics"],
        ["api_access", "analytics", "integrations"],
        ["api_access", "analytics", "integrations", "support"],
        ["api_access", "analytics", "integrations", "support", "white_label"],
    ]
    tiers = ["starter", "growth", "enterprise"]

    requests = []
    for i in range(50):
        requests.append({
            "id": f"req_{i:03d}",
            "product_name": products[i % len(products)],
            "current_price": random.uniform(29, 299),
            "competitors": ["comp_a", "comp_b"],
            "customer_segment": segments[i % len(segments)],
            "features": features[i % len(features)],
            "feature_count": len(features[i % len(features)]),
            "tier": tiers[i % len(tiers)],
        })
    return requests


def score_requests(requests: list[dict[str, Any]], max_requests: int, settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Score and sort requests by priority."""
    scored: list[dict[str, Any]] = []
    for request in requests:
        enriched = dict(request)
        enriched["priority_score"] = compute_priority_score(enriched, settings)
        scored.append(enriched)

    scored.sort(key=lambda item: float(item["priority_score"]), reverse=True)
    return scored[:max_requests]
