"""Smoke tests for SaaS Pricing Intelligence API."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import PricingIntelligenceEngine, PricingEngine, PricingRequest


def test_pricing_request_creation():
    """Test PricingRequest creation."""
    request = PricingRequest(
        product_name="Test Product",
        current_price=99.0,
        competitors=["competitor_a", "competitor_b"],
        customer_segment="smb",
        features=["api_access", "analytics"],
    )
    assert request.product_name == "Test Product"
    assert request.current_price == 99.0
    assert request.customer_segment == "smb"


def test_pricing_intelligence_engine_analyze():
    """Test PricingIntelligenceEngine.analyze()."""
    engine = PricingIntelligenceEngine()
    request = PricingRequest(
        product_name="Test SaaS",
        current_price=99.0,
        competitors=["comp_a", "comp_b"],
        customer_segment="smb",
        features=["api_access", "analytics", "support"],
    )

    recommendation = engine.analyze(request)

    assert recommendation.product_name == "Test SaaS"
    assert recommendation.recommended_price > 0
    assert 0 < recommendation.confidence <= 1
    assert recommendation.mrr_projection > 0
    assert len(recommendation.key_factors) > 0


def test_pricing_engine_tiers():
    """Test PricingEngine tier pricing."""
    assert PricingEngine.get_price("starter") == 49
    assert PricingEngine.get_price("growth") == 199
    assert PricingEngine.get_price("enterprise") == 999


def test_pricing_engine_revenue_calculation():
    """Test revenue calculation from subscriptions."""
    subscriptions = [
        {"tier": "starter"},
        {"tier": "growth"},
        {"tier": "enterprise"},
    ]
    revenue = PricingEngine.calculate_revenue(subscriptions)
    assert revenue == 49 + 199 + 999


def test_enterprise_segment():
    """Test enterprise segment pricing."""
    engine = PricingIntelligenceEngine()
    request = PricingRequest(
        product_name="Enterprise Tool",
        current_price=299.0,
        competitors=["comp_a"],
        customer_segment="enterprise",
        features=["api_access", "analytics", "integrations", "support", "white_label", "sso"],
    )

    recommendation = engine.analyze(request)
    assert recommendation.recommended_price > 200  # Enterprise should be premium


def test_startup_segment():
    """Test startup segment pricing."""
    engine = PricingIntelligenceEngine()
    request = PricingRequest(
        product_name="Startup Tool",
        current_price=29.0,
        competitors=["comp_a"],
        customer_segment="startup",
        features=["api_access"],
    )

    recommendation = engine.analyze(request)
    assert recommendation.recommended_price < 150  # Startup should be value-priced
