"""Core application logic for SaaS Pricing Intelligence API."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class PricingRequest:
    """Request for pricing intelligence analysis."""
    product_name: str
    current_price: float
    competitors: list[str]
    customer_segment: str
    features: list[str]
    mrr_target: float | None = None


@dataclass
class PricingRecommendation:
    """Response with pricing recommendation."""
    product_name: str
    recommended_price: float
    confidence: float
    price_change_percent: float
    mrr_projection: float
    key_factors: list[str]
    competitor_positioning: str


class PricingIntelligenceEngine:
    """AI-powered SaaS pricing intelligence engine."""

    def analyze(self, request: PricingRequest) -> PricingRecommendation:
        """Generate pricing recommendation for SaaS product."""

        # Base confidence based on data quality (simulated)
        confidence = 0.72 + random.uniform(-0.05, 0.08)
        confidence = max(0.65, min(confidence, 0.85))

        # Calculate recommended price based on multiple factors
        base_recommendation = self._compute_base_recommendation(request)
        competitor_adjustment = self._compute_competitor_adjustment(request)
        segment_adjustment = self._compute_segment_adjustment(request)
        feature_adjustment = self._compute_feature_adjustment(request)

        # Weighted combination
        recommended_price = (
            base_recommendation * 0.35 +
            competitor_adjustment * 0.30 +
            segment_adjustment * 0.20 +
            feature_adjustment * 0.15
        )

        # Ensure minimum price floor
        recommended_price = max(9.99, recommended_price)

        # Round to 2 decimal places
        recommended_price = round(recommended_price, 2)

        # Calculate percent change
        if request.current_price > 0:
            price_change_percent = ((recommended_price - request.current_price) / request.current_price) * 100
        else:
            price_change_percent = 0.0

        # Project MRR based on typical SaaS metrics
        estimated_customers = 1000  # Simulated customer base
        mrr_projection = recommended_price * estimated_customers

        # Generate key factors
        key_factors = self._generate_factors(request, recommended_price)

        # Determine competitor positioning
        positioning = self._determine_positioning(request, recommended_price)

        return PricingRecommendation(
            product_name=request.product_name,
            recommended_price=recommended_price,
            confidence=round(confidence, 4),
            price_change_percent=round(price_change_percent, 2),
            mrr_projection=round(mrr_projection, 2),
            key_factors=key_factors,
            competitor_positioning=positioning,
        )

    def _compute_base_recommendation(self, request: PricingRequest) -> float:
        """Compute base price recommendation."""
        # Start with current price as baseline
        base = request.current_price

        # Add growth factor (typical SaaS annual price increase)
        base *= 1.08

        # Add value-based premium based on feature count
        feature_premium = len(request.features) * 5.0
        base += feature_premium

        return base

    def _compute_competitor_adjustment(self, request: PricingRequest) -> float:
        """Adjust based on competitor pricing."""
        if not request.competitors:
            return request.current_price

        # Simulate competitor price range
        competitor_prices = [random.uniform(29, 299) for _ in request.competitors]
        avg_competitor_price = sum(competitor_prices) / len(competitor_prices)

        # Target slightly below to slightly above average based on features
        target_position = 1.05 if len(request.features) > 5 else 0.95

        return avg_competitor_price * target_position

    def _compute_segment_adjustment(self, request: PricingRequest) -> float:
        """Adjust based on customer segment."""
        segment_multipliers = {
            "startup": 0.6,
            "smb": 1.0,
            "mid-market": 2.5,
            "enterprise": 5.0,
        }

        multiplier = segment_multipliers.get(request.customer_segment, 1.0)
        base_price = 99.0  # Industry baseline

        return base_price * multiplier

    def _compute_feature_adjustment(self, request: PricingRequest) -> float:
        """Adjust based on feature set."""
        # Value-based pricing for features
        feature_values = {
            "api_access": 25.0,
            "analytics": 20.0,
            "integrations": 15.0,
            "support": 30.0,
            "custom_domain": 10.0,
            "white_label": 50.0,
            "sso": 35.0,
            "audit_logs": 15.0,
        }

        total_feature_value = 0.0
        for feature in request.features:
            feature_lower = feature.lower()
            for key, value in feature_values.items():
                if key in feature_lower:
                    total_feature_value += value
                    break

        # Base price + feature value
        return 49.0 + total_feature_value

    def _generate_factors(self, request: PricingRequest, recommended: float) -> list[str]:
        """Generate key contributing factors."""
        factors = []

        if len(request.features) > 5:
            factors.append("Premium feature set justifies higher pricing")

        if request.customer_segment == "enterprise":
            factors.append("Enterprise segment supports premium pricing")

        if len(request.competitors) >= 3:
            factors.append("Competitive landscape analysis applied")

        if recommended > request.current_price:
            factors.append("Market positioning allows price increase")
        else:
            factors.append("Competitive pressure suggests optimization")

        # Always add some factors
        if not factors:
            factors = [
                "Value-based pricing model applied",
                "Market benchmark analysis completed",
            ]

        return factors[:4]  # Limit to 4 factors

    def _determine_positioning(self, request: PricingRequest, recommended: float) -> str:
        """Determine competitive positioning."""
        if recommended > 200:
            return "premium"
        elif recommended > 99:
            return "mid-market"
        else:
            return "value"


class PricingEngine:
    """Pricing engine for subscription tiers."""

    TIERS = {
        "starter": {
            "monthly_price": 49,
            "api_calls_per_month": 100,
            "features": ["basic_analytics", "email_support"],
        },
        "growth": {
            "monthly_price": 199,
            "api_calls_per_month": 1000,
            "features": ["advanced_analytics", "competitor_tracking", "priority_support"],
        },
        "enterprise": {
            "monthly_price": 999,
            "api_calls_per_month": -1,  # unlimited
            "features": ["custom_models", "dedicated_support", "sla"],
        },
    }

    @classmethod
    def get_price(cls, tier: str) -> float:
        """Get monthly price for a tier."""
        return cls.TIERS.get(tier, {}).get("monthly_price", 49)

    @classmethod
    def calculate_revenue(cls, subscriptions: list[dict[str, Any]]) -> float:
        """Calculate total monthly revenue from subscriptions."""
        total = 0.0
        for sub in subscriptions:
            tier = sub.get("tier", "starter")
            total += cls.get_price(tier)
        return total
