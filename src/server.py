"""Flask API server for SaaS Pricing Intelligence API."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from functools import wraps

from flask import Flask, jsonify, request, g
from flask_cors import CORS

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger("saas_pricing_api")

# Import the pricing engine
import sys
sys.path.insert(0, str(Path(__file__).parent))

from app import PricingIntelligenceEngine, PricingRequest, PricingEngine
from benchmarks import (
    calculate_charm_pricing,
    calculate_price_elasticity,
    categorize_product_nlp,
    detect_price_trends,
    analyze_competitor_pricing,
)
from competitor_data import get_competitor_enrichment, get_aggregated_competitor_pricing

app = Flask(__name__)
CORS(app)

# Track startup time for health checks
STARTUP_TIME = time.time()

# Initialize the pricing engine
pricing_engine = PricingIntelligenceEngine()

# Global error handler for uncaught exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle uncaught exceptions with proper logging and error response."""
    error_id = f"ERR-{int(time.time() * 1000)}"
    logger.exception(f"Unhandled exception [{error_id}]: {str(e)}")
    return jsonify({
        "error": "Internal server error",
        "error_code": error_id,
        "message": "An unexpected error occurred. Please try again later.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 500


# Handle 404 errors
@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 errors with consistent error response."""
    return jsonify({
        "error": "Not found",
        "error_code": "NOT_FOUND",
        "message": f"The requested resource '{request.path}' was not found.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 404


# Handle 405 Method Not Allowed
@app.errorhandler(405)
def handle_method_not_allowed(e):
    """Handle 405 errors with consistent error response."""
    return jsonify({
        "error": "Method not allowed",
        "error_code": "METHOD_NOT_ALLOWED",
        "message": f"The {request.method} method is not allowed for this endpoint.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 405


# Handle 400 Bad Request
@app.errorhandler(400)
def handle_bad_request(e):
    """Handle 400 errors with consistent error response."""
    return jsonify({
        "error": "Bad request",
        "error_code": "BAD_REQUEST",
        "message": str(e) if str(e) else "The request was invalid or malformed.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 400


# Track request start time for logging
@app.before_request
def before_request_logging():
    """Track request start time for performance logging."""
    g.request_start_time = time.time()


# Add structured logging for all requests
@app.after_request
def log_request(response):
    """Log request details with response time."""
    # Calculate response time
    if hasattr(g, 'request_start_time'):
        response_time = (time.time() - g.request_start_time) * 1000  # ms
    else:
        response_time = 0

    # Log structured request info
    logger.info(json.dumps({
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "response_time_ms": round(response_time, 2),
        "remote_addr": request.remote_addr,
        "user_agent": request.headers.get("User-Agent", "")[:50]
    }))

    return response


# Add rate limit headers to authenticated responses
@app.after_request
def add_rate_limit_headers(response):
    """Add rate limit headers to authenticated API requests."""
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if api_key and api_key in API_KEYS:
        tier = API_KEYS[api_key].get("tier", "free")
        calls = API_KEYS[api_key].get("calls", 0)
        limit = RATE_LIMITS.get(tier, 100)
        if limit == -1:
            # Unlimited tier
            response.headers['X-RateLimit-Limit'] = 'unlimited'
            response.headers['X-RateLimit-Remaining'] = 'unlimited'
        else:
            response.headers['X-RateLimit-Limit'] = str(limit)
            remaining = max(0, limit - calls)
            response.headers['X-RateLimit-Remaining'] = str(remaining)
            # Add reset timestamp (start of next month)
            now = datetime.now(timezone.utc)
            if now.month == 12:
                reset_time = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                reset_time = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
            response.headers['X-RateLimit-Reset'] = str(int(reset_time.timestamp()))
    return response

# Simple API key storage (in production, use a database)
# Format: {api_key: {"tier": str, "calls": int, "created": timestamp, "last_used": timestamp}}
API_KEYS: dict[str, dict[str, Any]] = {}

# Rate limits per tier
RATE_LIMITS = {
    "free": 100,      # 100 calls/month
    "starter": 100,   # 100 calls/month
    "developer": 500, # 500 calls/month
    "premium": 2000,  # 2000 calls/month
    "growth": 1000,   # 1000 calls/month
    "enterprise": -1, # unlimited
}

# Admin API key (set via environment)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "admin-secret-key-change-in-production")

# Valid email regex pattern
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# Public endpoints that don't require API key
PUBLIC_ENDPOINTS = {
    "/api/health", "/api/products", "/api/categories", "/api/pricing/tiers",
    "/api/trends", "/", "/api/docs", "/api/stats",
    "/api/categorize", "/api/trends/analyze", "/api/competitors/analyze"
}

# Public endpoint patterns (prefixes)
PUBLIC_ENDPOINT_PREFIXES = {"/api/products/", "/api/competitors/", "/api/price-history/"}


def is_public_endpoint(path: str) -> bool:
    """Check if endpoint is public (doesn't require API key)."""
    if path in PUBLIC_ENDPOINTS:
        return True
    for prefix in PUBLIC_ENDPOINT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def validate_pagination_params(page: Any, limit: Any) -> tuple[int, int]:
    """Validate and sanitize pagination parameters."""
    try:
        page = int(page) if page is not None else 1
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise ValueError("Page and limit must be integers")

    if page < 1:
        page = 1
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    return page, limit


def validate_email(email: str) -> bool:
    """Validate email format."""
    return bool(EMAIL_PATTERN.match(email)) if email else False


def create_error_response(message: str, status_code: int, error_type: str = "error") -> tuple[dict, int]:
    """Create a standardized error response."""
    return (
        {"error": message, "error_type": error_type, "status_code": status_code},
        status_code
    )


def require_api_key(f):
    """Decorator to require valid API key for endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if endpoint is public
        if is_public_endpoint(request.path):
            return f(*args, **kwargs)

        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")

        if not api_key:
            logger.warning(f"API request missing key: {request.method} {request.path}")
            return jsonify({
                "error": "API key required",
                "error_code": "API_KEY_MISSING",
                "message": "Include X-API-Key header or api_key query parameter.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 401

        # Check if key exists
        if api_key not in API_KEYS:
            logger.warning(f"API request with invalid key: {request.method} {request.path}")
            return jsonify({
                "error": "Invalid API key",
                "error_code": "API_KEY_INVALID",
                "message": "The provided API key is not valid or has been revoked.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }), 401

        key_data = API_KEYS[api_key]

        # Check rate limit (skip for enterprise)
        tier = key_data.get("tier", "free")
        limit = RATE_LIMITS.get(tier, 100)

        if limit > 0:
            calls = key_data.get("calls", 0)
            if calls >= limit:
                logger.warning(f"Rate limit exceeded for tier {tier}: {request.method} {request.path}")
                # Calculate reset time (start of next month)
                now = datetime.now(timezone.utc)
                if now.month == 12:
                    reset_time = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    reset_time = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
                reset_timestamp = int(reset_time.timestamp())
                return jsonify({
                    "error": f"Rate limit exceeded for {tier} tier. Upgrade to continue.",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "limit": limit,
                    "used": calls,
                    "retry_after": reset_timestamp,
                    "reset_date": reset_time.isoformat(),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }), 429

        # Update usage stats
        API_KEYS[api_key]["calls"] = key_data.get("calls", 0) + 1
        API_KEYS[api_key]["last_used"] = time.time()

        # Store key data in Flask's g object for the endpoint
        g.api_key_data = key_data

        logger.info(f"API request authorized: {request.method} {request.path} (tier: {tier})")
        return f(*args, **kwargs)
    return decorated_function


@app.route("/api/keys", methods=["POST"])
def create_api_key():
    """Create a new API key. Requires admin key or no authentication for demo.

    Request Body (JSON):
        tier (str): API tier - free, starter, growth, or enterprise (default: "free")
        email (str): User's email for the key (optional)

    Response:
        api_key (str): The new API key (shown only once)
        tier (str): The assigned tier
        monthly_calls_limit (int): API call limit for the tier
    """
    auth_key = request.headers.get("X-API-Key")

    # For demo purposes, allow key creation without auth (in production, require admin key)
    # To enable admin-only key creation, uncomment below:
    # if auth_key != ADMIN_API_KEY:
    #     return jsonify({"error": "Admin API key required"}), 403

    data = request.get_json() or {}
    tier = data.get("tier", "free")

    if tier not in RATE_LIMITS:
        logger.warning(f"API key creation failed: Invalid tier: {tier}")
        return jsonify({"error": f"Invalid tier. Choose from: {list(RATE_LIMITS.keys())}"}), 400

    logger.info(f"Creating new API key with tier: {tier}")

    # Generate API key
    api_key = f"spk_{secrets.token_urlsafe(32)}"

    # Store the key
    API_KEYS[api_key] = {
        "tier": tier,
        "calls": 0,
        "created": time.time(),
        "last_used": None,
        "email": data.get("email", ""),
    }

    logger.info(f"API key created: tier={tier}, email={data.get('email', '')}")
    return jsonify({
        "api_key": api_key,
        "tier": tier,
        "monthly_calls_limit": RATE_LIMITS[tier],
        "message": "Save this API key - it won't be shown again!"
    }), 201


@app.route("/api/keys/<api_key>", methods=["GET"])
def get_key_info(api_key):
    """Get information about an API key."""
    auth_key = request.headers.get("X-API-Key")

    # Allow users to check their own key or admin to check any key
    if auth_key != ADMIN_API_KEY and auth_key != api_key:
        return jsonify({"error": "Not authorized to view this key"}), 403

    if api_key not in API_KEYS:
        return jsonify({"error": "API key not found"}), 404

    key_data = API_KEYS[api_key]
    tier = key_data.get("tier", "free")

    return jsonify({
        "tier": tier,
        "calls_used": key_data.get("calls", 0),
        "calls_limit": RATE_LIMITS[tier],
        "created": key_data.get("created"),
        "last_used": key_data.get("last_used"),
    })


@app.route("/api/keys/<api_key>", methods=["DELETE"])
def revoke_api_key(api_key):
    """Revoke/delete an API key."""
    auth_key = request.headers.get("X-API-Key")

    if auth_key != ADMIN_API_KEY and auth_key != api_key:
        return jsonify({"error": "Not authorized to revoke this key"}), 403

    if api_key not in API_KEYS:
        return jsonify({"error": "API key not found"}), 404

    del API_KEYS[api_key]
    return jsonify({"message": "API key revoked successfully"})


@app.route("/api/keys", methods=["GET"])
def list_api_keys():
    """List all API keys (admin only)."""
    auth_key = request.headers.get("X-API-Key")

    if auth_key != ADMIN_API_KEY:
        return jsonify({"error": "Admin API key required"}), 403

    keys_info = []
    for key, data in API_KEYS.items():
        keys_info.append({
            "key": key[:12] + "..." + key[-4:],  # Masked key
            "tier": data.get("tier"),
            "calls": data.get("calls", 0),
            "created": data.get("created"),
        })

    return jsonify({"keys": keys_info, "total": len(keys_info)})

from src.load_products import load_products_db

# Load product database from data/products.json (2000 products, 149 categories)
PRODUCTS_DB = load_products_db()

# Pricing history storage (in production, use a database)
# Key: product_id, Value: list of {"timestamp": ISO8601, "monthly": float, "annual": float}
PRICING_HISTORY: dict[int, list[dict]] = {}

def record_pricing_history(product_id: int, pricing: dict) -> None:
    """Record a pricing snapshot for a product.

    Args:
        product_id: The product ID
        pricing: The pricing dictionary with 'monthly' and/or 'annual' keys
    """
    if product_id not in PRICING_HISTORY:
        PRICING_HISTORY[product_id] = []

    # Only record if pricing has changed from the last entry
    history = PRICING_HISTORY[product_id]
    if history:
        last_entry = history[-1]
        last_monthly = last_entry.get("monthly")
        new_monthly = pricing.get("monthly")
        # Skip if no meaningful change
        if last_monthly is not None and new_monthly is not None and last_monthly == new_monthly:
            return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monthly": pricing.get("monthly"),
        "annual": pricing.get("annual"),
    }
    PRICING_HISTORY[product_id].append(entry)

    # Limit history to 1000 entries per product to prevent memory bloat
    if len(PRICING_HISTORY[product_id]) > 1000:
        PRICING_HISTORY[product_id] = PRICING_HISTORY[product_id][-1000:]

# Add more products to reach 1000+.
CATEGORIES = [
    # Core categories
    "Communication", "Productivity", "Design", "Development", "Project Management",
    "CRM", "Marketing", "Customer Support", "Video Conferencing", "File Storage",
    "Analytics", "HR", "Finance", "Security", "Education", "DevOps", "No-Code",
    "Website Builder", "E-Commerce",
    "Accounting", "ERP", "Legal", "Healthcare", "Real Estate", "Manufacturing",
    "Retail", "Logistics", "Travel", "Food & Beverage", "Gaming", "Media",
    "Entertainment", "Sports", "Non-Profit", "Government", "Education Tech",
    "Martech", "Sales Enablement", "Data Management", "Cloud Infrastructure",
    "Cybersecurity", "Identity Management", "Compliance", "Business Intelligence",
    "Machine Learning", "AI Platforms", "Automation", "Workflow", "Collaboration",
    "Remote Work", "Employee Engagement", "Talent Management", "Recruiting",
    "Onboarding", "Learning Management", "Corporate Training", "Knowledge Management",
    "IT Management", "Network Monitoring", "Help Desk", "Asset Management",
    "Contract Management", "Invoice Management", "Payment Processing", "Banking",
    "Insurance", "Investment", "Trading", "Risk Management", "Fraud Detection",
    "Email Marketing", "SMS Marketing", "Push Notifications", "Social Media",
    "SEO", "Content Marketing", "Influencer Marketing", "Affiliate Marketing",
    "Virtual Events", "Webinars", "Online Courses", "LMS", "Assessment",
    "Survey", "Feedback", "Customer Experience", "User Research", "Prototyping",
    "User Testing", "Accessibility", "Conversion Optimization", "A/B Testing",
    "Personalization", "Recommendation Engines", "Sentiment Analysis", "NLP",
    "Chatbots", "Virtual Assistants", "Computer Vision", "Image Editing",
    "Video Editing", "3D Modeling", "Animation", "AR/VR", "CAD", "BIM",
    "Product Lifecycle", "Supply Chain", "Warehouse", "Fleet Management", "POS",
    "Inventory Management", "Order Management", "Returns Management", "WMS",
    # New categories for expansion
    "API Management", "Customer Data Platform", "IT Service Management",
    "Contract Lifecycle Management", "Digital Adoption Platform",
    "Revenue Intelligence", "Observability", "Endpoint Protection",
    "Email Security", "Backup & Recovery", "Container Management",
    "Cloud Security", "Application Performance", "Digital Experience"
]

NAME_PREFIXES = [
    "Nimbus", "Atlas", "Pulse", "Vertex", "Orbit", "Foundry", "Cobalt",
    "Summit", "Meridian", "Harbor", "Signal", "Forge", "Scale", "Nova"
]
NAME_SUFFIXES = [
    "Cloud", "Suite", "Flow", "HQ", "Ops", "Stack", "Sync", "Pilot",
    "Bridge", "Core", "One", "Labs", "Desk", "Grid"
]
CATEGORY_KEYWORDS = {
    "Communication": ["Connect", "Message", "Voice", "Inbox"],
    "Productivity": ["Docs", "Tasks", "Workspace", "Notes"],
    "Design": ["Studio", "Canvas", "Mockup", "Creative"],
    "Development": ["Dev", "Code", "Build", "Deploy"],
    "Project Management": ["Project", "Roadmap", "Sprint", "Planner"],
    "CRM": ["CRM", "Pipeline", "Sales", "Lead"],
    "Marketing": ["Campaign", "Growth", "Attribution", "Audience"],
    "Customer Support": ["Support", "Help", "Service", "Ticket"],
    "Video Conferencing": ["Meet", "Call", "Video", "Webinar"],
    "File Storage": ["Storage", "Drive", "Vault", "Files"],
    "Analytics": ["Analytics", "Insights", "Metrics", "BI"],
    "HR": ["People", "Talent", "HR", "Payroll"],
    "Finance": ["Finance", "Ledger", "Billing", "Revenue"],
    "Security": ["Shield", "Trust", "Secure", "Identity"],
    "Education": ["Learn", "Academy", "Class", "Course"],
    "DevOps": ["DevOps", "Infra", "Release", "Pipeline"],
    "No-Code": ["NoCode", "Builder", "Automation", "Workflow"],
    "Website Builder": ["Site", "Web", "Page", "CMS"],
    "E-Commerce": ["Commerce", "Store", "Checkout", "Catalog"],
    # New category keywords
    "API Management": ["API", "Gateway", "Portal", "Developer"],
    "Customer Data Platform": ["CDP", "Unified", "Profile", "Audience"],
    "IT Service Management": ["ITSM", "Ticket", "Service", "Incident"],
    "Contract Lifecycle Management": ["Contract", "Agreement", "Legal", "Compliance"],
    "Digital Adoption Platform": ["Adoption", "Walkthrough", "Guidance", "Onboarding"],
    "Revenue Intelligence": ["Revenue", "Forecast", "Billing", "Subscription"],
    "Observability": ["Monitor", "Logs", "Metrics", "Tracing"],
    "Endpoint Protection": ["Endpoint", "Antivirus", "Malware", "Threat"],
    "Email Security": ["Email", "Phishing", "Protection", "Spam"],
    "Backup & Recovery": ["Backup", "Recovery", "Restore", "Disaster"],
    "Container Management": ["Container", "Kubernetes", "Docker", "Orchestration"],
    "Cloud Security": ["Cloud", "CSPM", "Posture", "Configuration"],
    "Application Performance": ["APM", "Performance", "Real User", "Synthetic"],
    "Digital Experience": ["DX", "Experience", "Journey", "Journey"]
}
FALLBACK_COMPETITORS = [
    "Slack", "Notion", "HubSpot", "Shopify", "Zendesk",
    "AWS", "Azure", "Google Cloud", "Snowflake", "Databricks",
    "Twilio", "SendGrid", "Stripe", "PagerDuty", "New Relic",
    "Splunk", "Datadog", "MongoDB", "PostgreSQL", "Redis"
]


def _build_generated_name(product_id: int, category: str) -> str:
    """Generate deterministic, SaaS-style names without generic placeholders."""
    prefix = NAME_PREFIXES[product_id % len(NAME_PREFIXES)]
    keyword_list = CATEGORY_KEYWORDS.get(category, ["Platform"])
    keyword = keyword_list[(product_id // 3) % len(keyword_list)]
    suffix = NAME_SUFFIXES[(product_id // 7) % len(NAME_SUFFIXES)]
    return f"{prefix} {keyword} {suffix}"


def _build_generated_product(product_id: int) -> dict[str, Any]:
    """Create a deterministic synthetic product record for catalog expansion."""
    category = CATEGORIES[product_id % len(CATEGORIES)]
    base_price = round(random.uniform(9, 299), 2)
    competitor_a = FALLBACK_COMPETITORS[product_id % len(FALLBACK_COMPETITORS)]
    competitor_b = FALLBACK_COMPETITORS[(product_id + 2) % len(FALLBACK_COMPETITORS)]
    return {
        "id": product_id,
        "name": _build_generated_name(product_id, category),
        "category": category,
        "pricing": {"monthly": base_price, "annual": round(base_price * 10, 2)},
        "features": ["feature1", "feature2", "feature3"],
        "price_history": [
            {"date": "2025-01", "monthly": round(base_price * 0.9, 2)},
            {"date": "2025-07", "monthly": round(base_price * 0.95, 2)},
            {"date": "2026-01", "monthly": base_price}
        ],
        "competitors": [competitor_a, competitor_b]
    }


# Fill non-static ID ranges and expand to 1000+ total products.
for i in range(81, 501):
    PRODUCTS_DB.append(_build_generated_product(i))

for i in range(621, 1101):
    PRODUCTS_DB.append(_build_generated_product(i))

# New products for expanded categories
for i in range(1101, 1351):
    PRODUCTS_DB.append(_build_generated_product(i))

PRODUCTS_DB.extend([
        # API Management (751-770)
        {"id": 751, "name": "Apigee", "category": "API Management", "pricing": {"monthly": 500, "annual": 5000}, "features": ["api_gateway", "analytics", "developer_portal"], "competitors": ["AWS API Gateway", "Kong", "MuleSoft"]},
        {"id": 752, "name": "Kong", "category": "API Management", "pricing": {"monthly": 99, "annual": 990}, "features": ["api_gateway", "plugins", "service_mesh"], "competitors": ["Apigee", "AWS API Gateway", "Tyk"]},
        {"id": 753, "name": "Tyk", "category": "API Management", "pricing": {"monthly": 75, "annual": 750}, "features": ["api_gateway", "analytics", "quota"], "competitors": ["Kong", "Apigee", "AWS API Gateway"]},
        {"id": 754, "name": "RapidAPI", "category": "API Management", "pricing": {"monthly": 0, "annual": 0}, "features": ["marketplace", "api_gateway", "monitoring"], "competitors": ["Postman", "APILayer", "MuleSoft"]},
        {"id": 755, "name": "Postman", "category": "API Management", "pricing": {"monthly": 14, "annual": 140}, "features": ["api_testing", "documentation", "monitoring"], "competitors": ["Insomnia", "SoapUI", "RapidAPI"]},
        {"id": 756, "name": "MuleSoft", "category": "API Management", "pricing": {"monthly": 400, "annual": 4000}, "features": ["integration", "api_management", "ipaas"], "competitors": ["Dell Boomi", "Workato", "Tibco"]},
        {"id": 757, "name": "Dell Boomi", "category": "API Management", "pricing": {"monthly": 250, "annual": 2500}, "features": ["ipaas", "api_management", "integration"], "competitors": ["MuleSoft", "Workato", "Informatica"]},
        {"id": 758, "name": "Workato", "category": "API Management", "pricing": {"monthly": 99, "annual": 990}, "features": ["ipaas", "integration", "automation"], "competitors": ["Zapier", "MuleSoft", "Dell Boomi"]},
        {"id": 759, "name": "DreamFactory", "category": "API Management", "pricing": {"monthly": 49, "annual": 490}, "features": ["api_generator", "swagger", "authentication"], "competitors": ["Postman", "Kong", "Tyk"]},
        {"id": 760, "name": "Stoplight", "category": "API Management", "pricing": {"monthly": 29, "annual": 290}, "features": ["api_design", "documentation", "mocking"], "competitors": ["Postman", "Swagger", "Redoc"]},

        # Data Science / ML (771-800)
        {"id": 761, "name": "DataRobot", "category": "Data Science", "pricing": {"monthly": 250, "annual": 2500}, "features": ["ml", "automl", "model_deployment"], "competitors": ["Dataiku", "H2O", "Google Vertex AI"]},
        {"id": 762, "name": "Dataiku", "category": "Data Science", "pricing": {"monthly": 200, "annual": 2000}, "features": ["data_prep", "ml", "collaboration"], "competitors": ["DataRobot", "Alteryx", "Trifacta"]},
        {"id": 763, "name": "H2O.ai", "category": "Data Science", "pricing": {"monthly": 100, "annual": 1000}, "features": ["automl", "ml", "deep_learning"], "competitors": ["DataRobot", "Dataiku", "Google Vertex AI"]},
        {"id": 764, "name": "Weights & Biases", "category": "Data Science", "pricing": {"monthly": 35, "annual": 350}, "features": ["ml_tracking", "visualization", "collaboration"], "competitors": ["MLflow", "Neptune", "Comet"]},
        {"id": 765, "name": "MLflow", "category": "Data Science", "pricing": {"monthly": 0, "annual": 0}, "features": ["ml_tracking", "model_registry", "deployment"], "competitors": ["Weights & Biases", "Neptune", "Kubeflow"]},
        {"id": 766, "name": "Databricks", "category": "Data Science", "pricing": {"monthly": 0.07, "annual": 0.84}, "features": ["spark", "lakehouse", "ml"], "competitors": ["Snowflake", "AWS EMR", "Google Dataproc"]},
        {"id": 767, "name": "Alteryx", "category": "Data Science", "pricing": {"monthly": 195, "annual": 1950}, "features": ["data_prep", "analytics", "automation"], "competitors": ["Trifacta", "Dataiku", "Talend"]},
        {"id": 768, "name": "Trifacta", "category": "Data Science", "pricing": {"monthly": 75, "annual": 750}, "features": ["data_prep", "wrangling", "profiling"], "competitors": ["Alteryx", "Dataiku", "Talend"]},
        {"id": 769, "name": "Datawrapper", "category": "Data Science", "pricing": {"monthly": 39, "annual": 390}, "features": ["charts", "maps", "tables"], "competitors": ["Flourish", "Tableau Public", "Google Data Studio"]},
        {"id": 770, "name": "Flourish", "category": "Data Science", "pricing": {"monthly": 24, "annual": 240}, "features": ["data_viz", "storytelling", "templates"], "competitors": ["Datawrapper", "Tableau", "Flourish"]},
        {"id": 771, "name": "Mode", "category": "Data Science", "pricing": {"monthly": 45, "annual": 450}, "features": ["analytics", "sql", "python"], "competitors": ["Tableau", "Looker", "Periscope"]},
        {"id": 772, "name": "Periscope Data", "category": "Data Science", "pricing": {"monthly": 125, "annual": 1250}, "features": ["analytics", "sql", "dashboards"], "competitors": ["Mode", "Looker", "Tableau"]},
        {"id": 773, "name": "Databox", "category": "Data Science", "pricing": {"monthly": 29, "annual": 290}, "features": ["analytics", "dashboards", "mobile"], "competitors": ["Geckoboard", "Klipfolio", "Tableau"]},
        {"id": 774, "name": "Geckoboard", "category": "Data Science", "pricing": {"monthly": 39, "annual": 390}, "features": ["dashboards", "tv_dashboard", "integrations"], "competitors": ["Databox", "Klipfolio", "Screenful"]},
        {"id": 775, "name": "Klipfolio", "category": "Data Science", "pricing": {"monthly": 30, "annual": 300}, "features": ["dashboards", "data_connections", "publishing"], "competitors": ["Databox", "Geckoboard", "Tableau"]},
        {"id": 776, "name": "Metabase", "category": "Data Science", "pricing": {"monthly": 0, "annual": 0}, "features": ["analytics", "dashboards", "query_builder"], "competitors": ["Superset", "Redash", "Looker"]},
        {"id": 777, "name": "Apache Superset", "category": "Data Science", "pricing": {"monthly": 0, "annual": 0}, "features": ["analytics", "viz", "sql_editor"], "competitors": ["Metabase", "Redash", "Tableau"]},
        {"id": 778, "name": "Redash", "category": "Data Science", "pricing": {"monthly": 0, "annual": 0}, "features": ["query_editor", "visualizations", "alerts"], "competitors": ["Metabase", "Superset", "Tableau"]},
        {"id": 779, "name": "ThoughtSpot", "category": "Data Science", "pricing": {"monthly": 200, "annual": 2000}, "features": ["analytics", "search", "ai"], "competitors": ["Tableau", "Qlik", "Looker"]},
        {"id": 780, "name": "Qlik", "category": "Data Science", "pricing": {"monthly": 30, "annual": 300}, "features": ["analytics", "data_engine", "associations"], "competitors": ["Tableau", "ThoughtSpot", "Power BI"]},

        # Legal Tech (801-820)
        {"id": 781, "name": "Clio", "category": "Legal", "pricing": {"monthly": 39, "annual": 390}, "features": ["case_management", "billing", "calendar"], "competitors": ["MyCase", "PracticePanther", "Lawyers.com"]},
        {"id": 782, "name": "MyCase", "category": "Legal", "pricing": {"monthly": 39, "annual": 390}, "features": ["case_management", "billing", "client_portal"], "competitors": ["Clio", "PracticePanther", "LawRocket"]},
        {"id": 783, "name": "PracticePanther", "category": "Legal", "pricing": {"monthly": 35, "annual": 350}, "features": ["case_management", "billing", "automation"], "competitors": ["Clio", "MyCase", "Amicus"]},
        {"id": 784, "name": "LegalZoom", "category": "Legal", "pricing": {"monthly": 0, "annual": 0}, "features": ["legal_forms", "llc", "consultation"], "competitors": ["Rocket Lawyer", "Nolo", "LegalShield"]},
        {"id": 785, "name": "Rocket Lawyer", "category": "Legal", "pricing": {"monthly": 39.99, "annual": 399.90}, "features": ["legal_forms", "contracts", "consultation"], "competitors": ["LegalZoom", "Nolo", "LegalZoom"]},
        {"id": 786, "name": "DocuSign", "category": "Legal", "pricing": {"monthly": 25, "annual": 250}, "features": ["esignatures", "contracts", "workflows"], "competitors": ["HelloSign", "PandaDoc", "Adobe Sign"]},
        {"id": 787, "name": "HelloSign", "category": "Legal", "pricing": {"monthly": 25, "annual": 250}, "features": ["esignatures", "templates", "api"], "competitors": ["DocuSign", "PandaDoc", "Adobe Sign"]},
        {"id": 788, "name": "PandaDoc", "category": "Legal", "pricing": {"monthly": 19, "annual": 190}, "features": ["proposals", "esignatures", "analytics"], "competitors": ["DocuSign", "HelloSign", "Adobe Sign"]},
        {"id": 789, "name": "Adobe Sign", "category": "Legal", "pricing": {"monthly": 24.99, "annual": 249.90}, "features": ["esignatures", "integration", "compliance"], "competitors": ["DocuSign", "HelloSign", "PandaDoc"]},
        {"id": 790, "name": "Ironclad", "category": "Legal", "pricing": {"monthly": 150, "annual": 1500}, "features": ["contract_lifecycle", "workflows", "analytics"], "competitors": ["DocuSign CLM", "Icertis", "SAP Ariba"]},
        {"id": 791, "name": "LawGeex", "category": "Legal", "pricing": {"monthly": 99, "annual": 990}, "features": ["contract_review", "ai", "compliance"], "competitors": ["Ironclad", "Kira", "Luminous"]},
        {"id": 792, "name": "Kira Systems", "category": "Legal", "pricing": {"monthly": 2000, "annual": 20000}, "features": ["contract_analysis", "ml", "reporting"], "competitors": ["LawGeex", "Ironclad", "Thought Machine"]},
        {"id": 793, "name": " Relativity", "category": "Legal", "pricing": {"monthly": 1500, "annual": 15000}, "features": ["ediscovery", "review", "analytics"], "competitors": ["Logikcull", "Everlaw", "Disco"]},
        {"id": 794, "name": "Logikcull", "category": "Legal", "pricing": {"monthly": 199, "annual": 1990}, "features": ["ediscovery", "instant_search", "compliance"], "competitors": ["Relativity", "Everlaw", "Disco"]},
        {"id": 795, "name": "Everlaw", "category": "Legal", "pricing": {"monthly": 250, "annual": 2500}, "features": ["ediscovery", "review", "collaboration"], "competitors": ["Relativity", "Logikcull", "Disco"]},
        {"id": 796, "name": "Lexicata", "category": "Legal", "pricing": {"monthly": 39, "annual": 390}, "features": ["client_intake", "case_management", "automation"], "competitors": ["Clio", "MyCase", "PracticePanther"]},
        {"id": 797, "name": "CARET", "category": "Legal", "pricing": {"monthly": 59, "annual": 590}, "features": ["practice_management", "billing", "crm"], "competitors": ["Clio", "MyCase", "Amicus"]},
        {"id": 798, "name": "Practice League", "category": "Legal", "pricing": {"monthly": 45, "annual": 450}, "features": ["case_management", "document", "billing"], "competitors": ["Clio", "MyCase", "Zola"]},
        {"id": 799, "name": "Bill4Time", "category": "Legal", "pricing": {"monthly": 29, "annual": 290}, "features": ["time_tracking", "billing", "accounting"], "competitors": ["Clio", "TimeSolv", "Rocket Matter"]},
        {"id": 800, "name": "TimeSolv", "category": "Legal", "pricing": {"monthly": 49, "annual": 490}, "features": ["time_tracking", "billing", "invoicing"], "competitors": ["Bill4Time", "Clio", "Rocket Matter"]},

        # Real Estate (821-850)
        {"id": 801, "name": "Zillow", "category": "Real Estate", "pricing": {"monthly": 0, "annual": 0}, "features": ["listings", "valuations", "agents"], "competitors": ["Realtor.com", "Redfin", "Trulia"]},
        {"id": 802, "name": "Redfin", "category": "Real Estate", "pricing": {"monthly": 0, "annual": 0}, "features": ["listings", "virtual_tours", "agent_match"], "competitors": ["Zillow", "Realtor.com", "Compass"]},
        {"id": 803, "name": "Compass", "category": "Real Estate", "pricing": {"monthly": 0, "annual": 0}, "features": ["agent_platform", "marketing", "tools"], "competitors": ["Zillow", "Redfin", "REX"]},
        {"id": 804, "name": "dotloop", "category": "Real Estate", "pricing": {"monthly": 49, "annual": 490}, "features": ["transaction_management", "e-signatures", "forms"], "competitors": ["DocuSign", "Skyslope", "RealPage"]},
        {"id": 805, "name": "Skyslope", "category": "Real Estate", "pricing": {"monthly": 60, "annual": 600}, "features": ["transaction_management", "compliance", "analytics"], "competitors": ["dotloop", "RealPage", "Zurple"]},
        {"id": 806, "name": "RealPage", "category": "Real Estate", "pricing": {"monthly": 1, "annual": 12}, "features": ["property_management", "leasing", "accounting"], "competitors": ["Buildium", "AppFolio", "Yardi"]},
        {"id": 807, "name": "Buildium", "category": "Real Estate", "pricing": {"monthly": 50, "annual": 500}, "features": ["property_management", "tenant_portal", "accounting"], "competitors": ["RealPage", "AppFolio", "Yardi"]},
        {"id": 808, "name": "AppFolio", "category": "Real Estate", "pricing": {"monthly": 50, "annual": 500}, "features": ["property_management", "leasing", "marketing"], "competitors": ["Buildium", "RealPage", "Yardi"]},
        {"id": 809, "name": "Yardi", "category": "Real Estate", "pricing": {"monthly": 3, "annual": 36}, "features": ["property_management", "investment", "accounting"], "competitors": ["Buildium", "RealPage", "AppFolio"]},
        {"id": 810, "name": "Matterport", "category": "Real Estate", "pricing": {"monthly": 49, "annual": 490}, "features": ["3d_tours", "virtual_walkthrough", "measurement"], "competitors": ["Zillow 3D", "Tours", "iStaging"]},
        {"id": 811, "name": "CoStar", "category": "Real Estate", "pricing": {"monthly": 150, "annual": 1500}, "features": ["commercial_listings", "analytics", "research"], "competitors": ["LoopNet", "Reonomy", "Crexi"]},
        {"id": 812, "name": "LoopNet", "category": "Real Estate", "pricing": {"monthly": 0, "annual": 0}, "features": ["commercial_listings", "search", "advertising"], "competitors": ["CoStar", "Crexi", "Reonomy"]},
        {"id": 813, "name": "CREXi", "category": "Real Estate", "pricing": {"monthly": 99, "annual": 990}, "features": ["commercial_listings", "marketing", "analytics"], "competitors": ["LoopNet", "CoStar", "Reonomy"]},
        {"id": 814, "name": "Reonomy", "category": "Real Estate", "pricing": {"monthly": 500, "annual": 5000}, "features": ["property_data", "analytics", "owner_info"], "competitors": ["CoStar", "CREXi", "LoopNet"]},
        {"id": 815, "name": "Boomtown", "category": "Real Estate", "pricing": {"monthly": 49, "annual": 490}, "features": ["crm", "lead_generation", "marketing"], "competitors": ["Zillow Premier Agent", "Boomtown ROI", "LISTHUB"]},
        {"id": 816, "name": "LISthub", "category": "Real Estate", "pricing": {"monthly": 99, "annual": 990}, "features": ["mls_distribution", "lead_capture", "analytics"], "competitors": ["Zillow", "Realtor.com", "Boomtown"]},
        {"id": 817, "name": "Top Producer", "category": "Real Estate", "pricing": {"monthly": 49.99, "annual": 499.90}, "features": ["crm", "marketing", "web_leads"], "competitors": ["Boomtown", "LionDesk", "RealGeeks"]},
        {"id": 818, "name": "LionDesk", "category": "Real Estate", "pricing": {"monthly": 29, "annual": 290}, "features": ["crm", "dialer", "marketing_automation"], "competitors": ["Top Producer", "Boomtown", "RealGeeks"]},
        {"id": 819, "name": "RealGeeks", "category": "Real Estate", "pricing": {"monthly": 399, "annual": 3990}, "features": ["crm", "idx_website", "lead_capture"], "competitors": ["Boomtown", "Top Producer", "Zillow Premier Agent"]},
        {"id": 820, "name": "Market Leader", "category": "Real Estate", "pricing": {"monthly": 49, "annual": 490}, "features": ["crm", "marketing", "website"], "competitors": ["Boomtown", "RealGeeks", "Zillow"]},

        # Healthcare (821-870 - now continuing)
        {"id": 821, "name": "Athenahealth", "category": "Healthcare", "pricing": {"monthly": 140, "annual": 1400}, "features": ["ehr", "billing", "patient_portal"], "competitors": ["Epic", "Cerner", "Allscripts"]},
        {"id": 822, "name": "Epic", "category": "Healthcare", "pricing": {"monthly": 500, "annual": 5000}, "features": ["ehr", "mychart", "care_guidance"], "competitors": ["Athenahealth", "Cerner", "Meditech"]},
        {"id": 823, "name": "Cerner", "category": "Healthcare", "pricing": {"monthly": 400, "annual": 4000}, "features": ["ehr", "population_health", "analytics"], "competitors": ["Epic", "Athenahealth", "Allscripts"]},
        {"id": 824, "name": "DrChrono", "category": "Healthcare", "pricing": {"monthly": 109, "annual": 1090}, "features": ["ehr", "billing", "telehealth"], "competitors": ["Athenahealth", "Kareo", "SimplePractice"]},
        {"id": 825, "name": "Kareo", "category": "Healthcare", "pricing": {"monthly": 79, "annual": 790}, "features": ["ehr", "billing", "patient_portal"], "competitors": ["DrChrono", "Athenahealth", "SimplePractice"]},
        {"id": 826, "name": "SimplePractice", "category": "Healthcare", "pricing": {"monthly": 29, "annual": 290}, "features": ["telehealth", "scheduling", "crm"], "competitors": ["TheraNest", "Kareo", "DrChrono"]},
        {"id": 827, "name": "TheraNest", "category": "Healthcare", "pricing": {"monthly": 39, "annual": 390}, "features": ["practice_management", "telehealth", "notes"], "competitors": ["SimplePractice", "Kareo", "TherapyNotes"]},
        {"id": 828, "name": "TherapyNotes", "category": "Healthcare", "pricing": {"monthly": 49, "annual": 490}, "features": ["ehr", "billing", "scheduling"], "competitors": ["TheraNest", "SimplePractice", "Kareo"]},
        {"id": 829, "name": "CareCloud", "category": "Healthcare", "pricing": {"monthly": 199, "annual": 1990}, "features": ["ehr", "r cm", "patient_engagement"], "competitors": ["Athenahealth", "Kareo", "DrChrono"]},
        {"id": 830, "name": "NextGen Healthcare", "category": "Healthcare", "pricing": {"monthly": 250, "annual": 2500}, "features": ["ehr", "pm", "data_exchange"], "competitors": ["Athenahealth", "Epic", "Cerner"]},
        {"id": 831, "name": "Practice Fusion", "category": "Healthcare", "pricing": {"monthly": 149, "annual": 1490}, "features": ["ehr", "e_prescribing", "lab_integration"], "competitors": ["Athenahealth", "DrChrono", "Kareo"]},
        {"id": 832, "name": "eClinicalWorks", "category": "Healthcare", "pricing": {"monthly": 250, "annual": 2500}, "features": ["ehr", "patient_portal", "billing"], "competitors": ["Athenahealth", "NextGen", "Cerner"]},
        {"id": 833, "name": "MEDITECH", "category": "Healthcare", "pricing": {"monthly": 300, "annual": 3000}, "features": ["ehr", "expanse", "clinicals"], "competitors": ["Epic", "Cerner", "Allscripts"]},
        {"id": 834, "name": "Allscripts", "category": "Healthcare", "pricing": {"monthly": 300, "annual": 3000}, "features": ["ehr", "precision_prescribing", "financials"], "competitors": ["Epic", "Cerner", "Athenahealth"]},
        {"id": 835, "name": "Solutionreach", "category": "Healthcare", "pricing": {"monthly": 299, "annual": 2990}, "features": ["patient_communication", "recall", "surveys"], "competitors": ["Luma Health", "Solutionreach", "DocuTap"]},
        {"id": 836, "name": "Luma Health", "category": "Healthcare", "pricing": {"monthly": 150, "annual": 1500}, "features": ["patient_engagement", "scheduling", "referrals"], "competitors": ["Solutionreach", "Phreesia", "Solutionreach"]},
        {"id": 837, "name": "Phreesia", "category": "Healthcare", "pricing": {"monthly": 95, "annual": 950}, "features": ["patient_intake", "payments", "registration"], "competitors": ["Luma Health", "Solutionreach", "DocuWare"]},
        {"id": 838, "name": "GetWellNetwork", "category": "Healthcare", "pricing": {"monthly": 200, "annual": 2000}, "features": ["patient_engagement", "interactive_care", "rounding"], "competitors": ["Solutionreach", "CipherHealth", "Voalte"]},
        {"id": 839, "name": "Voalte", "category": "Healthcare", "pricing": {"monthly": 50, "annual": 500}, "features": ["mobile_communication", "alerts", "secure_messaging"], "competitors": ["Spok", "TigerConnect", "Microsoft Teams"]},
        {"id": 840, "name": "Spok", "category": "Healthcare", "pricing": {"monthly": 300, "annual": 3000}, "features": ["clinical_communications", "on_call", "alerting"], "competitors": ["Voalte", "TigerConnect", "PerfectServe"]},

        {"id": 841, "name": "Marketo", "category": "Marketing Automation", "pricing": {"monthly": 895, "annual": 8950}, "features": ["lead_management", "email_marketing", "analytics"], "competitors": ["HubSpot", "Pardot", "Salesforce Marketing Cloud"]},
        {"id": 842, "name": "Pardot", "category": "Marketing Automation", "pricing": {"monthly": 1000, "annual": 10000}, "features": ["b2b_marketing", "lead_generation", "roi"], "competitors": ["Marketo", "HubSpot", "Salesforce Marketing Cloud"]},
        {"id": 843, "name": "ActiveCampaign", "category": "Marketing Automation", "pricing": {"monthly": 29, "annual": 290}, "features": ["marketing_automation", "crm", "email"], "competitors": ["Mailchimp", "HubSpot", "Klaviyo"]},
        {"id": 844, "name": "GetResponse", "category": "Marketing Automation", "pricing": {"monthly": 15, "annual": 150}, "features": ["email_marketing", "automation", "landing_pages"], "competitors": ["Mailchimp", "ActiveCampaign", "ConvertKit"]},
        {"id": 845, "name": "AWeber", "category": "Marketing Automation", "pricing": {"monthly": 19, "annual": 190}, "features": ["email_marketing", "automation", "landing_pages"], "competitors": ["Mailchimp", "GetResponse", "ConvertKit"]},
        {"id": 846, "name": "Drip", "category": "Marketing Automation", "pricing": {"monthly": 39, "annual": 390}, "features": ["ecommerce_marketing", "automation", "analytics"], "competitors": ["Klaviyo", "ActiveCampaign", "Mailchimp"]},
        {"id": 847, "name": "ConvertKit", "category": "Marketing Automation", "pricing": {"monthly": 29, "annual": 290}, "features": ["creator_marketing", "email", "landing_pages"], "competitors": ["Mailchimp", "ActiveCampaign", "GetResponse"]},
        {"id": 848, "name": "Sendinblue", "category": "Marketing Automation", "pricing": {"monthly": 25, "annual": 250}, "features": ["email", "sms", "marketing_automation"], "competitors": ["Mailchimp", "Klaviyo", "ActiveCampaign"]},
        {"id": 849, "name": "Omnisend", "category": "Marketing Automation", "pricing": {"monthly": 16, "annual": 160}, "features": ["ecommerce", "email", "sms"], "competitors": ["Klaviyo", "Drip", "Mailchimp"]},
        {"id": 850, "name": "Keap", "category": "Marketing Automation", "pricing": {"monthly": 159, "annual": 1590}, "features": ["crm", "marketing_automation", "payments"], "competitors": ["HubSpot", "ActiveCampaign", "Infusionsoft"]},
        {"id": 851, "name": "Infusionsoft", "category": "Marketing Automation", "pricing": {"monthly": 199, "annual": 1990}, "features": ["crm", "marketing_automation", "ecommerce"], "competitors": ["HubSpot", "Keap", "ActiveCampaign"]},
        {"id": 852, "name": "SharpSpring", "category": "Marketing Automation", "pricing": {"monthly": 350, "annual": 3500}, "features": ["marketing_automation", "crm", "analytics"], "competitors": ["HubSpot", "Pardot", "Marketo"]},
        {"id": 853, "name": "Mautic", "category": "Marketing Automation", "pricing": {"monthly": 0, "annual": 0}, "features": ["marketing_automation", "email", "analytics"], "competitors": ["HubSpot", "Marketo", "ActiveCampaign"]},
        {"id": 854, "name": "EngageBay", "category": "Marketing Automation", "pricing": {"monthly": 15, "annual": 150}, "features": ["crm", "marketing_automation", "helpdesk"], "competitors": ["HubSpot", "Zoho", "Freshworks"]},
        {"id": 855, "name": "Nutshell", "category": "Marketing Automation", "pricing": {"monthly": 19, "annual": 190}, "features": ["crm", "marketing_automation", "sales"], "competitors": ["HubSpot", "Pipedrive", "Freshworks"]},
        {"id": 856, "name": "Amity", "category": "Marketing Automation", "pricing": {"monthly": 99, "annual": 990}, "features": ["customer_success", "automation", "analytics"], "competitors": ["Gainsight", "Totango", "ChurnZero"]},
        {"id": 857, "name": "Gainsight", "category": "Marketing Automation", "pricing": {"monthly": 150, "annual": 1500}, "features": ["customer_success", "nps", "analytics"], "competitors": ["Totango", "ChurnZero", "Amity"]},
        {"id": 858, "name": "Customer.io", "category": "Marketing Automation", "pricing": {"monthly": 99, "annual": 990}, "features": ["messaging", "automation", "segmentation"], "competitors": ["Braze", "Iterative", "Leanplum"]},
        {"id": 859, "name": "Braze", "category": "Marketing Automation", "pricing": {"monthly": 100, "annual": 1000}, "features": ["customer_engagement", "messaging", "analytics"], "competitors": ["Customer.io", "Leanplum", "OneSignal"]},
        {"id": 860, "name": "Iterable", "category": "Marketing Automation", "pricing": {"monthly": 150, "annual": 1500}, "features": ["cross_channel", "personalization", "workflows"], "competitors": ["Braze", "Customer.io", "SendGrid"]},

        # Social Media Management (861-900)
        {"id": 861, "name": "Hootsuite", "category": "Social Media", "pricing": {"monthly": 29, "annual": 290}, "features": ["scheduling", "analytics", "monitoring"], "competitors": ["Buffer", "Sprout Social", "Later"]},
        {"id": 862, "name": "Buffer", "category": "Social Media", "pricing": {"monthly": 15, "annual": 150}, "features": ["scheduling", "analytics", "publishing"], "competitors": ["Hootsuite", "Later", "Sprout Social"]},
        {"id": 863, "name": "Sprout Social", "category": "Social Media", "pricing": {"monthly": 99, "annual": 990}, "features": ["publishing", "analytics", "engagement"], "competitors": ["Hootsuite", "Buffer", "Later"]},
        {"id": 864, "name": "Later", "category": "Social Media", "pricing": {"monthly": 18, "annual": 180}, "features": ["scheduling", "visual_calendar", "analytics"], "competitors": ["Buffer", "Hootsuite", "Planoly"]},
        {"id": 865, "name": "Loomly", "category": "Social Media", "pricing": {"monthly": 26, "annual": 260}, "features": ["scheduling", "ideas", "analytics"], "competitors": ["Buffer", "Later", "Hootsuite"]},
        {"id": 866, "name": "Planoly", "category": "Social Media", "pricing": {"monthly": 9.99, "annual": 99.90}, "features": ["visual_planner", "hashtags", "analytics"], "competitors": ["Later", "Preview", "Unfold"]},
        {"id": 867, "name": "Tailwind", "category": "Social Media", "pricing": {"monthly": 15, "annual": 150}, "features": ["pinterest", "instagram", "scheduling"], "competitors": ["Later", "Buffer", "Hootsuite"]},
        {"id": 868, "name": "SocialBee", "category": "Social Media", "pricing": {"monthly": 25, "annual": 250}, "features": ["content_categories", "scheduling", "analytics"], "competitors": ["Buffer", "Later", "Hootsuite"]},
        {"id": 869, "name": "CoSchedule", "category": "Social Media", "pricing": {"monthly": 40, "annual": 400}, "features": ["marketing_calendar", "social_scheduling", "analytics"], "competitors": ["Hootsuite", "Asana", "Monday.com"]},
        {"id": 870, "name": "Agorapulse", "category": "Social Media", "pricing": {"monthly": 49, "annual": 490}, "features": ["scheduling", "inbox", "reporting"], "competitors": ["Hootsuite", "Sprout Social", "Buffer"]},
        {"id": 871, "name": "MeetEdgar", "category": "Social Media", "pricing": {"monthly": 49, "annual": 490}, "features": ["content_library", "scheduling", "automation"], "competitors": ["Buffer", "Hootsuite", "Later"]},
        {"id": 872, "name": "Sendible", "category": "Social Media", "pricing": {"monthly": 29, "annual": 290}, "features": ["scheduling", "analytics", "client_management"], "competitors": ["Hootsuite", "Sprout Social", "Agorapulse"]},
        {"id": 873, "name": "Iconosquare", "category": "Social Media", "pricing": {"monthly": 29, "annual": 290}, "features": ["instagram_analytics", "reporting", "competitors"], "competitors": ["Sprout Social", "Later", "Hootsuite"]},
        {"id": 874, "name": "RivalIQ", "category": "Social Media", "pricing": {"monthly": 79, "annual": 790}, "features": ["competitor_analysis", "social_analytics", "benchmarking"], "competitors": ["Sprout Social", "Iconosquare", "Synthesio"]},
        {"id": 875, "name": "Synthesio", "category": "Social Media", "pricing": {"monthly": 500, "annual": 5000}, "features": ["social_listening", "analytics", "reporting"], "competitors": ["Brandwatch", "Mention", "Talkwalker"]},
        {"id": 876, "name": "Brandwatch", "category": "Social Media", "pricing": {"monthly": 400, "annual": 4000}, "features": ["social_listening", "analytics", "influencers"], "competitors": ["Mention", "Synthesio", "Talkwalker"]},
        {"id": 877, "name": "Mention", "category": "Social Media", "pricing": {"monthly": 99, "annual": 990}, "features": ["social_listening", "alerts", "reporting"], "competitors": ["Brandwatch", "Synthesio", "Talkwalker"]},
        {"id": 878, "name": "Awario", "category": "Social Media", "pricing": {"monthly": 79, "annual": 790}, "features": ["real_time_monitoring", "sentiment", "leads"], "competitors": ["Mention", "Brandwatch", "Talkwalker"]},
        {"id": 879, "name": "Talkwalker", "category": "Social Media", "pricing": {"monthly": 400, "annual": 4000}, "features": ["social_listening", "analytics", "ai"], "competitors": ["Brandwatch", "Mention", "Synthesio"]},
        {"id": 880, "name": "Sprinklr", "category": "Social Media", "pricing": {"monthly": 1500, "annual": 15000}, "features": ["social_management", "content", "advertising"], "competitors": ["Hootsuite", "Sprout Social", "Khoros"]},

        # Video / Webinar (881-920)
        {"id": 881, "name": "Vidyard", "category": "Video", "pricing": {"monthly": 15, "annual": 150}, "features": ["video_hosting", "analytics", "personalization"], "competitors": ["Loom", "Wistia", "Vimeo"]},
        {"id": 882, "name": "Wistia", "category": "Video", "pricing": {"monthly": 99, "annual": 990}, "features": ["video_hosting", "analytics", "lead_capture"], "competitors": ["Vidyard", "Vimeo", "YouTube"]},
        {"id": 883, "name": "Vimeo", "category": "Video", "pricing": {"monthly": 12, "annual": 120}, "features": ["video_hosting", "streaming", "analytics"], "competitors": ["YouTube", "Wistia", "Vidyard"]},
        {"id": 884, "name": "Kaltura", "category": "Video", "pricing": {"monthly": 150, "annual": 1500}, "features": ["video_platform", "streaming", "analytics"], "competitors": ["Vimeo", "Brightcove", "Ooyala"]},
        {"id": 885, "name": "Brightcove", "category": "Video", "pricing": {"monthly": 199, "annual": 1990}, "features": ["video_platform", "streaming", "monetization"], "competitors": ["Kaltura", "Vimeo", "Ooyala"]},
        {"id": 886, "name": "Livestream", "category": "Video", "pricing": {"monthly": 159, "annual": 1590}, "features": ["live_streaming", "broadcasting", "analytics"], "competitors": ["Vimeo", "YouTube", "Restream"]},
        {"id": 887, "name": "Restream", "category": "Video", "pricing": {"monthly": 39, "annual": 390}, "features": ["multi_platform_streaming", "scheduling", "analytics"], "competitors": ["Livestream", "StreamYard", "YouTube"]},
        {"id": 888, "name": "StreamYard", "category": "Video", "pricing": {"monthly": 25, "annual": 250}, "features": ["live_streaming", "branding", "multi_stream"], "competitors": ["Restream", "OBS", "Zoom"]},
        {"id": 889, "name": "Camtasia", "category": "Video", "pricing": {"monthly": 12.42, "annual": 149}, "features": ["screen_recording", "video_editing", "sharing"], "competitors": ["OBS", "Loom", "Screenflow"]},
        {"id": 890, "name": "Screenflow", "category": "Video", "pricing": {"monthly": 9.99, "annual": 99.90}, "features": ["screen_recording", "editing", "publishing"], "competitors": ["Camtasia", "Loom", "OBS"]},
        {"id": 891, "name": "Demio", "category": "Webinar", "pricing": {"monthly": 38, "annual": 380}, "features": ["webinar_platform", "automation", "analytics"], "competitors": ["Zoom", "GoToWebinar", "WebinarJam"]},
        {"id": 892, "name": "EverWebinar", "category": "Webinar", "pricing": {"monthly": 49, "annual": 490}, "features": ["automated_webinars", "scheduling", "engagement"], "competitors": ["Demio", "Zoom", "GoToWebinar"]},
        {"id": 893, "name": "GoToWebinar", "category": "Webinar", "pricing": {"monthly": 89, "annual": 890}, "features": ["webinars", "automation", "analytics"], "competitors": ["Zoom", "Webex", "Demio"]},
        {"id": 894, "name": "Webex", "category": "Webinar", "pricing": {"monthly": 13.50, "annual": 135}, "features": ["video_conferencing", "webinars", "meetings"], "competitors": ["Zoom", "GoToWebinar", "Microsoft Teams"]},
        {"id": 895, "name": "ClickMeeting", "category": "Webinar", "pricing": {"monthly": 30, "annual": 300}, "features": ["webinars", "automations", "recordings"], "competitors": ["GoToWebinar", "Zoom", "Demio"]},
        {"id": 896, "name": "BigMarker", "category": "Webinar", "pricing": {"monthly": 39, "annual": 390}, "features": ["webinar_platform", "landing_pages", "automation"], "competitors": ["GoToWebinar", "Zoom", "Demio"]},
        {"id": 897, "name": "Zuum", "category": "Webinar", "pricing": {"monthly": 37, "annual": 370}, "features": ["webinars", "engagement", "automation"], "competitors": ["Demio", "GoToWebinar", "ClickMeeting"]},
        {"id": 898, "name": "eWebinar", "category": "Webinar", "pricing": {"monthly": 99, "annual": 990}, "features": ["automated_webinars", "scheduling", "interactions"], "competitors": ["EverWebinar", "Demio", "Zoom"]},
        {"id": 899, "name": "StealthSeminar", "category": "Webinar", "pricing": {"monthly": 99, "annual": 990}, "features": ["automated_live", "evergreen", "analytics"], "competitors": ["EverWebinar", "eWebinar", "Demio"]},
        {"id": 900, "name": "Livestorm", "category": "Webinar", "pricing": {"monthly": 39, "annual": 390}, "features": ["webinars", "polls", "q_and_a"], "competitors": ["Zoom", "GoToWebinar", "Demio"]},

        # ITSM / Help Desk (901-940)
        {"id": 901, "name": "ServiceNow", "category": "ITSM", "pricing": {"monthly": 100, "annual": 1000}, "features": ["itsm", "itom", "workflows"], "competitors": ["Jira Service Management", "BMC Helix", "Cherwell"]},
        {"id": 902, "name": "Jira Service Management", "category": "ITSM", "pricing": {"monthly": 20, "annual": 200}, "features": ["itsm", "helpdesk", "asset_management"], "competitors": ["ServiceNow", "Freshservice", "Zendesk"]},
        {"id": 903, "name": "Freshservice", "category": "ITSM", "pricing": {"monthly": 29, "annual": 290}, "features": ["itsm", "helpdesk", "asset_management"], "competitors": ["Jira Service Management", "ServiceNow", "Zendesk"]},
        {"id": 904, "name": "BMC Helix", "category": "ITSM", "pricing": {"monthly": 150, "annual": 1500}, "features": ["itsm", "itom", "analytics"], "competitors": ["ServiceNow", "Cherwell", "Jira Service Management"]},
        {"id": 905, "name": "Cherwell", "category": "ITSM", "pricing": {"monthly": 95, "annual": 950}, "features": ["itsm", "csm", "asset_management"], "competitors": ["ServiceNow", "BMC Helix", "Jira Service Management"]},
        {"id": 906, "name": "SolarWinds Service Desk", "category": "ITSM", "pricing": {"monthly": 109, "annual": 1090}, "features": ["itsm", "helpdesk", "asset_management"], "competitors": ["ServiceNow", "Freshservice", "Jira Service Management"]},
        {"id": 907, "name": "ManageEngine ServiceDesk Plus", "category": "ITSM", "pricing": {"monthly": 45, "annual": 450}, "features": ["itsm", "helpdesk", "asset_management"], "competitors": ["ServiceNow", "Jira Service Management", "Freshservice"]},
        {"id": 908, "name": "SysAid", "category": "ITSM", "pricing": {"monthly": 29, "annual": 290}, "features": ["itsm", "helpdesk", "asset_management"], "competitors": ["ServiceNow", "Freshservice", "Jira Service Management"]},
        {"id": 909, "name": "Jira Service Management", "category": "ITSM", "pricing": {"monthly": 20, "annual": 200}, "features": ["service_desk", "asset_management", "slack_integration"], "competitors": ["Zendesk", "Freshservice", "ServiceNow"]},
        {"id": 910, "name": "TOPdesk", "category": "ITSM", "pricing": {"monthly": 40, "annual": 400}, "features": ["itsm", "eas", "helpdesk"], "competitors": ["ServiceNow", "Cherwell", "Freshservice"]},
        {"id": 911, "name": "Spiceworks", "category": "ITSM", "pricing": {"monthly": 0, "annual": 0}, "features": ["helpdesk", "inventory", "monitoring"], "competitors": ["Zendesk", "Freshdesk", "Jira Service Management"]},
        {"id": 912, "name": "Vision Helpdesk", "category": "ITSM", "pricing": {"monthly": 29, "annual": 290}, "features": ["helpdesk", "ticketing", "canned_responses"], "competitors": ["Zendesk", "Freshdesk", "Freshservice"]},
        {"id": 913, "name": "HappyFox", "category": "ITSM", "pricing": {"monthly": 29, "annual": 290}, "features": ["helpdesk", "ticketing", "automation"], "competitors": ["Zendesk", "Freshdesk", "Jira Service Management"]},
        {"id": 914, "name": "Support.com", "category": "ITSM", "pricing": {"monthly": 49, "annual": 490}, "features": ["helpdesk", "remote_support", "l1_support"], "competitors": ["Zendesk", "Freshdesk", "Bmc"]},
        {"id": 915, "name": "SysCloud", "category": "ITSM", "pricing": {"monthly": 60, "annual": 600}, "features": ["gsuite_backup", "security", "archiving"], "competitors": ["Spanning", "Backupify", "AvePoint"]},
        {"id": 916, "name": "Jira Asset Manager", "category": "ITSM", "pricing": {"monthly": 7, "annual": 70}, "features": ["asset_management", "inventory", "tracking"], "competitors": ["ServiceNow", "Freshservice", "SolarWinds"]},
        {"id": 917, "name": "Asset Panda", "category": "ITSM", "pricing": {"monthly": 45, "annual": 450}, "features": ["asset_tracking", "maintenance", "checkouts"], "competitors": ["ServiceNow", "Freshservice", "SolarWinds"]},
        {"id": 918, "name": "Snipe-it", "category": "ITSM", "pricing": {"monthly": 0, "annual": 0}, "features": ["asset_tracking", "licenses", "accessories"], "competitors": ["Asset Panda", "ServiceNow", "Freshservice"]},
        {"id": 919, "name": "Pulseway", "category": "ITSM", "pricing": {"monthly": 8, "annual": 80}, "features": ["remote_monitoring", "patch_management", "alerts"], "competitors": ["SolarWinds", "Atera", "NinjaRMM"]},
        {"id": 920, "name": "Atera", "category": "ITSM", "pricing": {"monthly": 39, "annual": 390}, "features": ["rpa", "monitoring", "billing"], "competitors": ["ConnectWise", "NinjaRMM", "SolarWinds"]},

        # E-commerce Platforms (921-960)
        {"id": 921, "name": "Shopify", "category": "E-Commerce", "pricing": {"monthly": 29, "annual": 290}, "features": ["online_store", "payments", "themes"], "competitors": ["WooCommerce", "BigCommerce", "Magento"]},
        {"id": 922, "name": "WooCommerce", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["wordpress_ecommerce", "plugins", "themes"], "competitors": ["Shopify", "BigCommerce", "Magento"]},
        {"id": 923, "name": "BigCommerce", "category": "E-Commerce", "pricing": {"monthly": 29.95, "annual": 299.50}, "features": ["saas_ecommerce", "headless", "b2b"], "competitors": ["Shopify", "Shopify Plus", "Magento"]},
        {"id": 924, "name": "Magento", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["enterprise_ecommerce", "flexibility", "extensions"], "competitors": ["Shopify Plus", "BigCommerce", "Salesforce Commerce Cloud"]},
        {"id": 925, "name": "Wix eCommerce", "category": "E-Commerce", "pricing": {"monthly": 27, "annual": 270}, "features": ["website_builder", "ecommerce", "templates"], "competitors": ["Shopify", "Squarespace", "BigCommerce"]},
        {"id": 926, "name": "Squarespace Commerce", "category": "E-Commerce", "pricing": {"monthly": 36, "annual": 360}, "features": ["website_builder", "ecommerce", "templates"], "competitors": ["Shopify", "Wix", "BigCommerce"]},
        {"id": 927, "name": "Volusion", "category": "E-Commerce", "pricing": {"monthly": 35, "annual": 350}, "features": ["ecommerce", "design", "marketing"], "competitors": ["Shopify", "BigCommerce", "3dcart"]},
        {"id": 928, "name": "3dcart", "category": "E-Commerce", "pricing": {"monthly": 29, "annual": 290}, "features": ["ecommerce", "seo", "marketing"], "competitors": ["Shopify", "BigCommerce", "Volusion"]},
        {"id": 929, "name": "PrestaShop", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["open_source", "modules", "themes"], "competitors": ["WooCommerce", "Magento", "OpenCart"]},
        {"id": 930, "name": "OpenCart", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["open_source", "extensions", "themes"], "competitors": ["WooCommerce", "Magento", "PrestaShop"]},
        {"id": 931, "name": "Salesforce Commerce Cloud", "category": "E-Commerce", "pricing": {"monthly": 150, "annual": 1500}, "features": ["enterprise", "b2c", "b2b"], "competitors": ["Magento", "Shopify Plus", "BigCommerce"]},
        {"id": 932, "name": "Oracle CX Commerce", "category": "E-Commerce", "pricing": {"monthly": 500, "annual": 5000}, "features": ["enterprise", "omnichannel", "ai"], "competitors": ["Salesforce", "Magento", "Shopify Plus"]},
        {"id": 933, "name": "Shopify Plus", "category": "E-Commerce", "pricing": {"monthly": 2000, "annual": 20000}, "features": ["enterprise", "wholesale", "automation"], "competitors": ["Salesforce Commerce Cloud", "Magento", "BigCommerce"]},
        {"id": 934, "name": "Ecwid", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["embeddable_cart", "wordpress", "social"], "competitors": ["WooCommerce", "Shopify", "BigCommerce"]},
        {"id": 935, "name": "Selly", "category": "E-Commerce", "pricing": {"monthly": 19, "annual": 190}, "features": ["wholesale", "b2b", "inventory"], "competitors": ["Shopify", "B2B Wave", "Ordoro"]},
        {"id": 936, "name": "B2B Wave", "category": "E-Commerce", "pricing": {"monthly": 79, "annual": 790}, "features": ["b2b_ecommerce", "wholesale", "pricing"], "competitors": ["Shopify", "Selly", "Ordoro"]},
        {"id": 937, "name": "OrderHive", "category": "E-Commerce", "pricing": {"monthly": 199, "annual": 1990}, "features": ["order_management", "inventory", "shipping"], "competitors": ["ShipStation", "Sellbrite", "Printful"]},
        {"id": 938, "name": "Sellbrite", "category": "E-Commerce", "pricing": {"monthly": 49, "annual": 490}, "features": ["multi_channel", "inventory", "listing"], "competitors": ["OrderHive", "Listingmirror", "Skubana"]},
        {"id": 939, "name": "Printful", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["print_on_demand", "fulfillment", "integration"], "competitors": ["Printify", "Gelato", "SPOD"]},
        {"id": 940, "name": "Printify", "category": "E-Commerce", "pricing": {"monthly": 0, "annual": 0}, "features": ["print_on_demand", "mockup_generator", "shipping"], "competitors": ["Printful", "Gelato", "SPOD"]},

        # Customer Feedback / Survey (941-980)
        {"id": 941, "name": "Typeform", "category": "Survey", "pricing": {"monthly": 25, "annual": 250}, "features": ["forms", "quizzes", "logic"], "competitors": ["JotForm", "Google Forms", "SurveyMonkey"]},
        {"id": 942, "name": "JotForm", "category": "Survey", "pricing": {"monthly": 24, "annual": 240}, "features": ["forms", "payments", "pdf"], "competitors": ["Typeform", "Google Forms", "Formstack"]},
        {"id": 943, "name": "SurveyMonkey", "category": "Survey", "pricing": {"monthly": 25, "annual": 250}, "features": ["surveys", "analysis", "templates"], "competitors": ["Typeform", "Qualtrics", "Google Forms"]},
        {"id": 944, "name": "Qualtrics", "category": "Survey", "pricing": {"monthly": 150, "annual": 1500}, "features": ["experience_management", "surveys", "analytics"], "competitors": ["SurveyMonkey", "Medallia", "Momentive"]},
        {"id": 945, "name": "Google Forms", "category": "Survey", "pricing": {"monthly": 0, "annual": 0}, "features": ["forms", "collect", "integrations"], "competitors": ["Typeform", "JotForm", "SurveyMonkey"]},
        {"id": 946, "name": "Formstack", "category": "Survey", "pricing": {"monthly": 50, "annual": 500}, "features": ["forms", "workflows", "security"], "competitors": ["JotForm", "Typeform", "DocuSign"]},
        {"id": 947, "name": "Cognito Forms", "category": "Survey", "pricing": {"monthly": 0, "annual": 0}, "features": ["forms", "calculations", "conditional_logic"], "competitors": ["Typeform", "JotForm", "Google Forms"]},
        {"id": 948, "name": "Paperform", "category": "Survey", "pricing": {"monthly": 18, "annual": 180}, "features": ["forms", "payments", "product_forms"], "competitors": ["Typeform", "JotForm", "Formstack"]},
        {"id": 949, "name": "Proprofs Survey", "category": "Survey", "pricing": {"monthly": 25, "annual": 250}, "features": ["surveys", "quizzes", "training"], "competitors": ["SurveyMonkey", "Typeform", "Qualtrics"]},
        {"id": 950, "name": "Zonka Feedback", "category": "Survey", "pricing": {"monthly": 29, "annual": 290}, "features": ["nps", "c sat", "ces"], "competitors": ["SurveyMonkey", "Qualtrics", "Medallia"]},
        {"id": 951, "name": "AskNicely", "category": "Customer Feedback", "pricing": {"monthly": 99, "annual": 990}, "features": ["nps", "real_time", "automation"], "competitors": ["Delighted", "Wootric", "Medallia"]},
        {"id": 952, "name": "Delighted", "category": "Customer Feedback", "pricing": {"monthly": 49, "annual": 490}, "features": ["nps", "surveys", "analytics"], "competitors": ["AskNicely", "Wootric", "SurveyMonkey"]},
        {"id": 953, "name": "Wootric", "category": "Customer Feedback", "pricing": {"monthly": 199, "annual": 1990}, "features": ["nps", "c sat", "analytics"], "competitors": ["Delighted", "AskNicely", "Medallia"]},
        {"id": 954, "name": "Medallia", "category": "Customer Feedback", "pricing": {"monthly": 1500, "annual": 15000}, "features": ["xm_platform", "analytics", "actions"], "competitors": ["Qualtrics", "SurveyMonkey", "AskNicely"]},
        {"id": 955, "name": "UserVoice", "category": "Customer Feedback", "pricing": {"monthly": 59, "annual": 590}, "features": ["feedback", "roadmapping", "prioritization"], "competitors": ["Product Hunt", "Canny", "FeatureUpvote"]},
        {"id": 956, "name": "Canny", "category": "Customer Feedback", "pricing": {"monthly": 39, "annual": 390}, "features": ["feedback", "roadmap", "voting"], "competitors": ["UserVoice", "Productboard", "FeatureUpvote"]},
        {"id": 957, "name": "Productboard", "category": "Customer Feedback", "pricing": {"monthly": 29, "annual": 290}, "features": ["roadmap", "feature_tracking", "insights"], "competitors": ["Aha", "Roadmunk", "Canny"]},
        {"id": 958, "name": "Aha!", "category": "Customer Feedback", "pricing": {"monthly": 59, "annual": 590}, "features": ["roadmaps", "strategy", "releases"], "competitors": ["Productboard", "Roadmunk", "Craft"]},
        {"id": 959, "name": "Roadmunk", "category": "Customer Feedback", "pricing": {"monthly": 29, "annual": 290}, "features": ["roadmapping", "timeline", "features"], "competitors": ["Aha!", "Productboard", "Craft"]},
        {"id": 960, "name": "Hotjar", "category": "Customer Feedback", "pricing": {"monthly": 32, "annual": 320}, "features": ["heatmaps", "recordings", "surveys"], "competitors": ["Crazy Egg", "FullStory", "Mouseflow"]},

        # Domain & Hosting (961-1000)
        {"id": 961, "name": "GoDaddy", "category": "Domain", "pricing": {"monthly": 0.99, "annual": 11.88}, "features": ["domain_registration", "web_hosting", "website_builder"], "competitors": ["Namecheap", "Domain.com", "Google Domains"]},
        {"id": 962, "name": "Namecheap", "category": "Domain", "pricing": {"monthly": 1.18, "annual": 12.98}, "features": ["domain_registration", "hosting", "ssl"], "competitors": ["GoDaddy", "Domain.com", "Google Domains"]},
        {"id": 963, "name": "Google Domains", "category": "Domain", "pricing": {"monthly": 12, "annual": 120}, "features": ["domain_registration", "dns", "privacy"], "competitors": ["GoDaddy", "Namecheap", "Name.com"]},
        {"id": 964, "name": "Name.com", "category": "Domain", "pricing": {"monthly": 3.98, "annual": 47.88}, "features": ["domain_registration", "hosting", "email"], "competitors": ["GoDaddy", "Namecheap", "Google Domains"]},
        {"id": 965, "name": "Hover", "category": "Domain", "pricing": {"monthly": 4.17, "annual": 49.98}, "features": ["domain_registration", "email_forwarding", "dns"], "competitors": ["Namecheap", "Google Domains", "Name.com"]},
        {"id": 966, "name": "Domain.com", "category": "Domain", "pricing": {"monthly": 3.75, "annual": 44.99}, "features": ["domain_registration", "hosting", "marketing"], "competitors": ["GoDaddy", "Namecheap", "Name.com"]},
        {"id": 967, "name": "Cloudflare", "category": "DNS", "pricing": {"monthly": 0, "annual": 0}, "features": ["cdn", "dns", "security"], "competitors": ["AWS CloudFront", "Akamai", "Fastly"]},
        {"id": 968, "name": "Amazon Route 53", "category": "DNS", "pricing": {"monthly": 0.50, "annual": 6}, "features": ["dns", "health_checks", "routing"], "competitors": ["Cloudflare", "Google DNS", "Azure DNS"]},
        {"id": 969, "name": "Azure DNS", "category": "DNS", "pricing": {"monthly": 0.40, "annual": 4.80}, "features": ["dns", "alias_records", "private_zones"], "competitors": ["AWS Route 53", "Cloudflare", "Google DNS"]},
        {"id": 970, "name": "Google Cloud DNS", "category": "DNS", "pricing": {"monthly": 0.40, "annual": 4.80}, "features": ["dns", "managed_zones", "dnssec"], "competitors": ["AWS Route 53", "Cloudflare", "Azure DNS"]},
        {"id": 971, "name": "DNSimple", "category": "DNS", "pricing": {"monthly": 5, "annual": 50}, "features": ["dns", "domains", "automation"], "competitors": ["Cloudflare", "Route 53", "DNS Made Easy"]},
        {"id": 972, "name": "DNS Made Easy", "category": "DNS", "pricing": {"monthly": 30, "annual": 300}, "features": ["dns", "performance", "analytics"], "competitors": ["Cloudflare", "Route 53", "DNSimple"]},
        {"id": 973, "name": "Comodo SSL", "category": "SSL", "pricing": {"monthly": 89, "annual": 890}, "features": ["ssl_certificate", "validation", "warranty"], "competitors": ["DigiCert", "GlobalSign", "Let's Encrypt"]},
        {"id": 974, "name": "DigiCert", "category": "SSL", "pricing": {"monthly": 175, "annual": 1750}, "features": ["ssl", "pki", "iot_security"], "competitors": ["Comodo", "GlobalSign", "Entrust"]},
        {"id": 975, "name": "GlobalSign", "category": "SSL", "pricing": {"monthly": 149, "annual": 1490}, "features": ["ssl", "identity", "document_signing"], "competitors": ["DigiCert", "Comodo", "Entrust"]},
        {"id": 976, "name": "Let's Encrypt", "category": "SSL", "pricing": {"monthly": 0, "annual": 0}, "features": ["free_ssl", "automation", "security"], "competitors": ["Comodo", "DigiCert", "GlobalSign"]},
        {"id": 977, "name": "Entrust", "category": "SSL", "pricing": {"monthly": 149, "annual": 1490}, "features": ["ssl", "code_signing", "authentication"], "competitors": ["DigiCert", "GlobalSign", "Comodo"]},
        {"id": 978, "name": "SiteGround", "category": "Hosting", "pricing": {"monthly": 14.99, "annual": 149.90}, "features": ["web_hosting", "wordpress", "speed"], "competitors": ["Bluehost", "HostGator", "WP Engine"]},
        {"id": 979, "name": "WP Engine", "category": "Hosting", "pricing": {"monthly": 30, "annual": 300}, "features": ["managed_wordpress", "staging", "performance"], "competitors": ["Kinsta", "SiteGround", "Bluehost"]},
        {"id": 980, "name": "Kinsta", "category": "Hosting", "pricing": {"monthly": 30, "annual": 300}, "features": ["managed_wordpress", "staging", "free_migration"], "competitors": ["WP Engine", "SiteGround", "Cloudways"]},
        {"id": 981, "name": "Bluehost", "category": "Hosting", "pricing": {"monthly": 15.95, "annual": 159.50}, "features": ["web_hosting", "wordpress", "domains"], "competitors": ["SiteGround", "HostGator", "GoDaddy"]},
        {"id": 982, "name": "HostGator", "category": "Hosting", "pricing": {"monthly": 10.95, "annual": 109.50}, "features": ["web_hosting", "wordpress", "website_builder"], "competitors": ["Bluehost", "SiteGround", "GoDaddy"]},
        {"id": 983, "name": "A2 Hosting", "category": "Hosting", "pricing": {"monthly": 14.99, "annual": 149.90}, "features": ["shared_hosting", "wordpress", "speed"], "competitors": ["SiteGround", "Bluehost", "HostGator"]},
        {"id": 984, "name": "InMotion Hosting", "category": "Hosting", "pricing": {"monthly": 14.99, "annual": 149.90}, "features": ["web_hosting", "vps", "dedicated"], "competitors": ["Bluehost", "HostGator", "A2 Hosting"]},
        {"id": 985, "name": "GreenGeeks", "category": "Hosting", "pricing": {"monthly": 10.95, "annual": 109.50}, "features": ["eco_hosting", "wordpress", "security"], "competitors": ["Bluehost", "SiteGround", "A2 Hosting"]},
        {"id": 986, "name": "DreamHost", "category": "Hosting", "pricing": {"monthly": 15.95, "annual": 159.50}, "features": ["web_hosting", "wordpress", "cloud"], "competitors": ["Bluehost", "SiteGround", "WP Engine"]},
        {"id": 987, "name": "Hostinger", "category": "Hosting", "pricing": {"monthly": 9.99, "annual": 99.90}, "features": ["web_hosting", "vps", "website_builder"], "competitors": ["Bluehost", "SiteGround", "GoDaddy"]},
        {"id": 988, "name": "Liquid Web", "category": "Hosting", "pricing": {"monthly": 59, "annual": 590}, "features": ["managed_hosting", "vps", "dedicated"], "competitors": ["WP Engine", "Kinsta", "SiteGround"]},
        {"id": 989, "name": "Rackspace", "category": "Hosting", "pricing": {"monthly": 500, "annual": 5000}, "features": ["managed_cloud", "dedicated", "hybrid"], "competitors": ["AWS", "Liquid Web", "IBM"]},
        {"id": 990, "name": "DigitalOcean", "category": "Cloud Hosting", "pricing": {"monthly": 5, "annual": 50}, "features": ["cloud", "droplets", "networking"], "competitors": ["AWS", "Linode", "Vultr"]},
        {"id": 991, "name": "Linode", "category": "Cloud Hosting", "pricing": {"monthly": 5, "annual": 50}, "features": ["cloud", "compute", "managed"], "competitors": ["DigitalOcean", "AWS", "Vultr"]},
        {"id": 992, "name": "Vultr", "category": "Cloud Hosting", "pricing": {"monthly": 5, "annual": 50}, "features": ["cloud", "compute", "block_storage"], "competitors": ["DigitalOcean", "Linode", "AWS"]},
        {"id": 993, "name": "Hetzner", "category": "Cloud Hosting", "pricing": {"monthly": 4.90, "annual": 49}, "features": ["cloud", "dedicated", "robot"], "competitors": ["DigitalOcean", "Linode", "Vultr"]},
        {"id": 994, "name": "UpCloud", "category": "Cloud Hosting", "pricing": {"monthly": 5, "annual": 50}, "features": ["cloud", "maxioes", "storage"], "competitors": ["DigitalOcean", "Linode", "Vultr"]},
        {"id": 995, "name": "Backblaze", "category": "Backup", "pricing": {"monthly": 7, "annual": 70}, "features": ["cloud_backup", "b2", "computer_backup"], "competitors": ["Carbonite", "CrashPlan", "IDrive"]},
        {"id": 996, "name": "Carbonite", "category": "Backup", "pricing": {"monthly": 6, "annual": 72}, "features": ["online_backup", "endpoint", "server"], "competitors": ["Backblaze", "CrashPlan", "IDrive"]},
        {"id": 997, "name": "SpiderOak", "category": "Backup", "pricing": {"monthly": 12, "annual": 120}, "features": ["zero_knowledge", "encryption", "sync"], "competitors": ["Backblaze", "Tresorit", "Sync.com"]},
        {"id": 998, "name": "pCloud", "category": "Backup", "pricing": {"monthly": 4.99, "annual": 49.90}, "features": ["cloud_storage", "encryption", "file_sync"], "competitors": ["Dropbox", "Google Drive", "iCloud"]},
        {"id": 999, "name": "Sync.com", "category": "Backup", "pricing": {"monthly": 8, "annual": 80}, "features": ["zero_knowledge", "file_sync", "sharing"], "competitors": ["pCloud", "Tresorit", "SpiderOak"]},
        {"id": 1000, "name": "IDrive", "category": "Backup", "pricing": {"monthly": 7.21, "annual": 72.10}, "features": ["online_backup", "cloud_storage", "device_backup"], "competitors": ["Carbonite", "Backblaze", "CrashPlan"]},

        # Additional niche SaaS products (1001-1050)
        {"id": 1001, "name": "Webflow CMS", "category": "CMS", "pricing": {"monthly": 19, "annual": 190}, "features": ["cms", "memberships", "ecommerce"], "competitors": ["Contentful", "Sanity", "Strapi"]},
        {"id": 1002, "name": "Contentful", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "api", "cdn"], "competitors": ["Sanity", "Strapi", "Prismic"]},
        {"id": 1003, "name": "Sanity", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "real_time", "studio"], "competitors": ["Contentful", "Strapi", "Prismic"]},
        {"id": 1004, "name": "Strapi", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "api", "customizable"], "competitors": ["Contentful", "Sanity", "Ghost"]},
        {"id": 1005, "name": "Prismic", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "slices", "preview"], "competitors": ["Contentful", "Sanity", "Storyblok"]},
        {"id": 1006, "name": "Storyblok", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "visual_editor", "components"], "competitors": ["Contentful", "Sanity", "Prismic"]},
        {"id": 1007, "name": "Ghost", "category": "CMS", "pricing": {"monthly": 25, "annual": 250}, "features": ["blog", "newsletter", "memberships"], "competitors": ["WordPress", "Substack", "Medium"]},
        {"id": 1008, "name": "DatoCMS", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "graph_ql", "media"], "competitors": ["Contentful", "Sanity", "Strapi"]},
        {"id": 1009, "name": "ButterCMS", "category": "CMS", "pricing": {"monthly": 29, "annual": 290}, "features": ["headless_cms", "api", "sdks"], "competitors": ["Contentful", "Sanity", "Ghost"]},
        {"id": 1010, "name": "Directus", "category": "CMS", "pricing": {"monthly": 0, "annual": 0}, "features": ["headless_cms", "sql", "realtime"], "competitors": ["Strapi", "Sanity", "Contentful"]},
        {"id": 1011, "name": "Platform.sh", "category": "DevOps", "pricing": {"monthly": 60, "annual": 600}, "features": ["paas", "git", "orchestration"], "competitors": ["Heroku", "Acquia", "Pantheon"]},
        {"id": 1012, "name": "Acquia", "category": "DevOps", "pricing": {"monthly": 100, "annual": 1000}, "features": ["drupal_cloud", "insight", "orchestrate"], "competitors": ["Pantheon", "Platform.sh", "WP Engine"]},
        {"id": 1013, "name": "Pantheon", "category": "DevOps", "pricing": {"monthly": 35, "annual": 350}, "features": ["wordpress", "drupal", "git"], "competitors": ["WP Engine", "Acquia", "Platform.sh"]},
        {"id": 1014, "name": "Fortrabbit", "category": "DevOps", "pricing": {"monthly": 12, "annual": 120}, "features": ["php_hosting", "scaling", "git"], "competitors": ["Platform.sh", "Heroku", "DigitalOcean"]},
        {"id": 1015, "name": "Laravel Forge", "category": "DevOps", "pricing": {"monthly": 19, "annual": 190}, "features": ["server_management", "deployment", "monitoring"], "competitors": ["DigitalOcean", "Linode", "AWS"]},
        {"id": 1016, "name": "Envoyer", "category": "DevOps", "pricing": {"monthly": 15, "annual": 150}, "features": ["zero_downtime", "hooks", "monitoring"], "competitors": ["Laravel Forge", "DeployBot", "Capistrano"]},
        {"id": 1017, "name": "DeployBot", "category": "DevOps", "pricing": {"monthly": 15, "annual": 150}, "features": ["deployment", "git", "rollback"], "competitors": ["Envoyer", "CircleCI", "Jenkins"]},
        {"id": 1018, "name": "Buddy", "category": "DevOps", "pricing": {"monthly": 25, "annual": 250}, "features": ["ci_cd", "deployment", "automation"], "competitors": ["GitHub Actions", "GitLab CI", "Jenkins"]},
        {"id": 1019, "name": "Semaphore", "category": "DevOps", "pricing": {"monthly": 29, "annual": 290}, "features": ["ci_cd", "parallelism", "deployment"], "competitors": ["CircleCI", "Travis CI", "Jenkins"]},
        {"id": 1020, "name": "Codeship", "category": "DevOps", "pricing": {"monthly": 49, "annual": 490}, "features": ["ci_cd", "deployments", "parallelism"], "competitors": ["CircleCI", "Travis CI", "Semaphore"]},
        {"id": 1021, "name": "LaunchDarkly", "category": "Developer Tools", "pricing": {"monthly": 75, "annual": 750}, "features": ["feature_flags", "targeting", "analytics"], "competitors": ["Optimizely", "Split", "Configu"]},
        {"id": 1022, "name": "Split", "category": "Developer Tools", "pricing": {"monthly": 50, "annual": 500}, "features": ["feature_flags", "data_phi", "experiments"], "competitors": ["LaunchDarkly", "Optimizely", "Statsig"]},
        {"id": 1023, "name": "Configu", "category": "Developer Tools", "pricing": {"monthly": 0, "annual": 0}, "features": ["config_management", "secrets", "cd"], "competitors": ["LaunchDarkly", "Split", "HashiCorp Vault"]},
        {"id": 1024, "name": "Sentry", "category": "Developer Tools", "pricing": {"monthly": 26, "annual": 260}, "features": ["error_monitoring", "performance", "releases"], "competitors": ["Datadog", "Bugsnag", "Rollbar"]},
        {"id": 1025, "name": "Bugsnag", "category": "Developer Tools", "pricing": {"monthly": 29, "annual": 290}, "features": ["error_monitoring", "stability", "releases"], "competitors": ["Sentry", "Datadog", "Rollbar"]},
        {"id": 1026, "name": "Rollbar", "category": "Developer Tools", "pricing": {"monthly": 21, "annual": 210}, "features": ["error_monitoring", "deploy_tracking", "integrations"], "competitors": ["Sentry", "Bugsnag", "Datadog"]},
        {"id": 1027, "name": "Raygun", "category": "Developer Tools", "pricing": {"monthly": 59, "annual": 590}, "features": ["error_monitoring", "real_user_monitoring", "crash_reporting"], "competitors": ["Sentry", "Bugsnag", "New Relic"]},
        {"id": 1028, "name": "Airbrake", "category": "Developer Tools", "pricing": {"monthly": 39, "annual": 390}, "features": ["error_monitoring", "deploy_tracking", "performance"], "competitors": ["Sentry", "Bugsnag", "Rollbar"]},
        {"id": 1029, "name": "Honeybadger", "category": "Developer Tools", "pricing": {"monthly": 24, "annual": 240}, "features": ["error_monitoring", "uptime", "checkins"], "competitors": ["Sentry", "Bugsnag", "Raygun"]},
        {"id": 1030, "name": "LogRocket", "category": "Developer Tools", "pricing": {"monthly": 29, "annual": 290}, "features": ["session_replay", "logs", "performance"], "competitors": ["FullStory", "Hotjar", "Sentry"]},
        {"id": 1031, "name": "PagerDuty", "category": "Monitoring", "pricing": {"monthly": 41, "annual": 410}, "features": ["incident_response", "on_call", "automation"], "competitors": ["Opsgenie", "VictorOps", "ServiceNow"]},
        {"id": 1032, "name": "Opsgenie", "category": "Monitoring", "pricing": {"monthly": 20, "annual": 200}, "features": ["alerting", "on_call", "escalation"], "competitors": ["PagerDuty", "VictorOps", "xMatters"]},
        {"id": 1033, "name": "VictorOps", "category": "Monitoring", "pricing": {"monthly": 30, "annual": 300}, "features": ["incident_management", "on_call", "chatops"], "competitors": ["PagerDuty", "Opsgenie", "ServiceNow"]},
        {"id": 1034, "name": "Grafana", "category": "Monitoring", "pricing": {"monthly": 8, "annual": 80}, "features": ["visualization", "monitoring", "alerting"], "competitors": ["Datadog", "New Relic", "Prometheus"]},
        {"id": 1035, "name": "Datadog", "category": "Monitoring", "pricing": {"monthly": 15, "annual": 150}, "features": ["monitoring", "security", "apm"], "competitors": ["New Relic", "Grafana", "Splunk"]},
        {"id": 1036, "name": "New Relic", "category": "Monitoring", "pricing": {"monthly": 99, "annual": 990}, "features": ["apm", "infrastructure", "logs"], "competitors": ["Datadog", "Splunk", "AppDynamics"]},
        {"id": 1037, "name": "AppDynamics", "category": "Monitoring", "pricing": {"monthly": 120, "annual": 1200}, "features": ["apm", "business_iq", "infrastructure"], "competitors": ["New Relic", "Datadog", "Splunk"]},
        {"id": 1038, "name": "Dynatrace", "category": "Monitoring", "pricing": {"monthly": 69, "annual": 690}, "features": ["apm", "infrastructure", "automation"], "competitors": ["New Relic", "Datadog", "AppDynamics"]},
        {"id": 1039, "name": "Instana", "category": "Monitoring", "pricing": {"monthly": 75, "annual": 750}, "features": ["apm", "infrastructure", "automation"], "competitors": ["Datadog", "New Relic", "Dynatrace"]},
        {"id": 1040, "name": "Synthwave", "category": "Monitoring", "pricing": {"monthly": 0, "annual": 0}, "features": ["synthetic_monitoring", "uptime", "ssl"], "competitors": ["Pingdom", "UptimeRobot", "Statuscake"]},
        {"id": 1041, "name": "Pingdom", "category": "Monitoring", "pricing": {"monthly": 14, "annual": 140}, "features": ["uptime", "real_user", "alerts"], "competitors": ["UptimeRobot", "Statuscake", "Better Uptime"]},
        {"id": 1042, "name": "UptimeRobot", "category": "Monitoring", "pricing": {"monthly": 0, "annual": 0}, "features": ["uptime_monitoring", "alerts", "status_pages"], "competitors": ["Pingdom", "Statuscake", "Better Uptime"]},
        {"id": 1043, "name": "Statuspage", "category": "Monitoring", "pricing": {"monthly": 39, "annual": 390}, "features": ["status_pages", "incident_communication", "subdomain"], "competitors": ["Cachet", "Instapage", "Statuso"]},
        {"id": 1044, "name": "Better Uptime", "category": "Monitoring", "pricing": {"monthly": 29, "annual": 290}, "features": ["on_call", "incident", "status_pages"], "competitors": ["PagerDuty", "Pingdom", "Statuspage"]},
        {"id": 1045, "name": "GitHub Actions", "category": "CI/CD", "pricing": {"monthly": 0, "annual": 0}, "features": ["ci_cd", "automation", "packages"], "competitors": ["GitLab CI", "CircleCI", "Jenkins"]},
        {"id": 1046, "name": "GitLab CI", "category": "CI/CD", "pricing": {"monthly": 0, "annual": 0}, "features": ["ci_cd", "devops", "registry"], "competitors": ["GitHub Actions", "CircleCI", "Jenkins"]},
        {"id": 1047, "name": "CircleCI", "category": "CI/CD", "pricing": {"monthly": 0, "annual": 0}, "features": ["ci_cd", "orbs", "contexts"], "competitors": ["GitHub Actions", "GitLab CI", "Travis CI"]},
        {"id": 1048, "name": "Travis CI", "category": "CI/CD", "pricing": {"monthly": 0, "annual": 0}, "features": ["ci_cd", "deployments", "github_integration"], "competitors": ["CircleCI", "GitHub Actions", "Jenkins"]},
        {"id": 1049, "name": "Jenkins", "category": "CI/CD", "pricing": {"monthly": 0, "annual": 0}, "features": ["ci_cd", "plugins", "automation"], "competitors": ["CircleCI", "GitHub Actions", "GitLab CI"]},
        {"id": 1050, "name": "TeamCity", "category": "CI/CD", "pricing": {"monthly": 45, "annual": 450}, "features": ["ci_cd", "build_config", "agents"], "competitors": ["Jenkins", "CircleCI", "Bamboo"]},
    ])


@app.route("/", methods=["GET"])
def serve_landing():
    """Serve the landing page."""
    landing_path = Path(__file__).parent.parent / "landing" / "index.html"
    if landing_path.exists():
        return landing_path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html"}
    return jsonify({"error": "Landing page not found"}), 404


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint.

    Returns:
        status (str): API status
        message (str): Status message
        version (str): API version
        uptime_seconds (float): Seconds since server started
        api_keys_count (int): Total number of API keys registered
        database (str): Database connection status
    """
    logger.debug("Health check endpoint called")

    # Calculate uptime
    uptime_seconds = time.time() - STARTUP_TIME

    # Count API keys
    api_keys_count = len(API_KEYS)

    # Check database (try to access the data directory)
    db_status = "ok"
    try:
        data_dir = Path(__file__).parent.parent / "data"
        if not data_dir.exists():
            db_status = "warning: data directory not found"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return jsonify({
        "status": "healthy",
        "message": "SaaS Pricing Intelligence API is running",
        "version": "1.0.0",
        "uptime_seconds": round(uptime_seconds, 2),
        "api_keys_count": api_keys_count,
        "database": db_status
    })


@app.route("/api/docs", methods=["GET"])
def api_docs():
    """Get API documentation.

    Returns comprehensive API documentation including all endpoints,
    their parameters, and response formats.
    """
    docs = {
        "title": "SaaS Pricing Intelligence API",
        "version": "1.0.0",
        "description": "AI-powered pricing intelligence for SaaS products. Get pricing recommendations, trend analysis, competitor insights, and market benchmarks.",
        "base_url": "/api",
        "endpoints": {
            "health": {
                "path": "/api/health",
                "method": "GET",
                "description": "Health check endpoint",
                "public": True,
                "response": {
                    "status": "ok",
                    "message": "SaaS Pricing Intelligence API is running",
                    "version": "1.0.0"
                }
            },
            "products_list": {
                "path": "/api/products",
                "method": "GET",
                "description": "List all products in the database",
                "public": True,
                "query_params": {
                    "page": "Page number (default 1)",
                    "limit": "Items per page (default 10, max 100)",
                    "category": "Filter by category"
                }
            },
            "products_detail": {
                "path": "/api/products/<int:product_id>",
                "method": "GET",
                "description": "Get detailed product information",
                "public": True,
                "path_params": {
                    "product_id": "Product ID"
                }
            },
            "categories": {
                "path": "/api/categories",
                "method": "GET",
                "description": "Get list of all product categories",
                "public": True
            },
            "pricing_tiers": {
                "path": "/api/pricing/tiers",
                "method": "GET",
                "description": "Get API pricing tiers",
                "public": True
            },
            "trends": {
                "path": "/api/trends",
                "method": "GET",
                "description": "Get current pricing trends by category",
                "public": True
            },
            "price_history": {
                "path": "/api/price-history/<int:product_id>",
                "method": "GET",
                "description": "Get historical pricing data with trend analysis",
                "public": True,
                "path_params": {
                    "product_id": "Product ID"
                },
                "query_params": {
                    "include_trend": "Include trend analysis (default true)"
                }
            },
            "categorize": {
                "path": "/api/categorize",
                "method": "POST",
                "description": "Categorize a product using NLP",
                "public": True,
                "request_body": {
                    "product_name": "Name of the product (required)",
                    "competitors": "List of competitor names (optional)",
                    "features": "List of product features (optional)"
                },
                "response": {
                    "primary_category": "Primary category identifier",
                    "category_name": "Human-readable category name",
                    "confidence": "Confidence score (0-1)",
                    "alternatives": "Alternative categories",
                    "method": "nlp_tfidf"
                }
            },
            "trends_analyze": {
                "path": "/api/trends/analyze",
                "method": "POST",
                "description": "Analyze price trends and forecast future prices",
                "public": True,
                "request_body": {
                    "historical_prices": "List of historical prices (min 3 required)",
                    "periods": "Number of periods to forecast (default 6)"
                },
                "response": {
                    "trend": "Overall trend classification",
                    "trend_direction": "Direction (increasing/decreasing/stable)",
                    "trend_strength": "Strength (strong/moderate/weak)",
                    "slope": "Linear regression slope",
                    "r_squared": "Coefficient of determination",
                    "volatility": "Price volatility",
                    "forecast": "Predicted future prices"
                }
            },
            "competitors_analyze": {
                "path": "/api/competitors/analyze",
                "method": "POST",
                "description": "Analyze competitor pricing and positioning",
                "public": True,
                "request_body": {
                    "product_name": "Your product name (required)",
                    "product_price": "Your current price (required)",
                    "competitor_prices": "List of competitor prices (required)"
                },
                "response": {
                    "positioning": "Market positioning",
                    "percentile": "Price percentile",
                    "competitor_stats": "Competitor statistics",
                    "market_pressure": "Market pressure score (0-100)",
                    "recommendation": "Strategic recommendation"
                }
            },
            "recommend": {
                "path": "/api/recommend",
                "method": "POST",
                "description": "Get pricing recommendation",
                "auth_required": True,
                "request_body": {
                    "product_name": "Product name (required)",
                    "current_price": "Current monthly price (required)",
                    "competitors": "List of competitor names",
                    "customer_segment": "startup/smb/mid-market/enterprise",
                    "features": "List of product features"
                }
            },
            "elasticity": {
                "path": "/api/elasticity",
                "method": "POST",
                "description": "Calculate price elasticity",
                "auth_required": True,
                "request_body": {
                    "current_price": "Current price (required)",
                    "customer_segment": "smb/startup/enterprise (required)",
                    "market_category": "Industry category (optional)"
                }
            },
            "charm_pricing": {
                "path": "/api/charm-pricing",
                "method": "POST",
                "description": "Calculate charm pricing",
                "auth_required": True,
                "request_body": {
                    "base_price": "Base price (required)",
                    "strategy": "classic/prestige/strategic/luxury/round"
                }
            },
            "create_key": {
                "path": "/api/keys",
                "method": "POST",
                "description": "Create a new API key",
                "request_body": {
                    "tier": "free/starter/growth/enterprise",
                    "email": "User email (optional)"
                }
            },
            "get_key_info": {
                "path": "/api/keys/<api_key>",
                "method": "GET",
                "description": "Get API key information"
            }
        },
        "authentication": {
            "description": "Most endpoints require API key authentication",
            "header": "X-API-Key",
            "query_param": "api_key"
        },
        "pricing_tiers": {
            "free": {"monthly_calls": 100, "price": "$0"},
            "starter": {"monthly_calls": 100, "price": "$49"},
            "growth": {"monthly_calls": 1000, "price": "$199"},
            "enterprise": {"monthly_calls": "unlimited", "price": "$999"}
        }
    }

    return jsonify(docs)


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get API statistics for landing page display."""
    logger.debug("Stats endpoint called")

    # Dynamically calculate stats from PRODUCTS_DB
    total_products = len(PRODUCTS_DB)
    unique_categories = len(set(p["category"] for p in PRODUCTS_DB))

    # Load signups for real-time counter
    signups_file = Path("data/signups.json")
    if signups_file.exists():
        with open(signups_file) as f:
            signups = json.load(f)
        total_signups = len(signups)
    else:
        total_signups = 0

    return jsonify({
        "products_indexed": total_products,
        "api_accuracy": 97,
        "uptime": 99.9,
        "market_data_value": "$247B",
        "active_signups": total_signups,
        "categories": unique_categories,
        "updated_at": datetime.now().isoformat()
    })


@app.route("/api/products", methods=["GET"])
def get_products():
    """Get all products with optional filtering.

    Query Parameters:
        page (int): Page number (default: 1)
        limit (int): Items per page (default: 10, max: 100)
        category (str): Filter by category name
        search (str): Search term to filter by product name
        min_price (float): Filter by minimum monthly price
        max_price (float): Filter by maximum monthly price
        sort_by (str): Sort by 'popularity' (default), 'price_low', 'price_high', 'newest', 'name'
    """
    try:
        page, limit = validate_pagination_params(
            request.args.get("page"),
            request.args.get("limit")
        )
    except ValueError as e:
        logger.warning(f"Invalid pagination params: {e}")
        return jsonify({"error": str(e)}), 400

    category = request.args.get("category")
    search = request.args.get("search", "").lower()
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    sort_by = request.args.get("sort_by", "popularity")

    # Validate category if provided
    if category and category not in CATEGORIES:
        return jsonify({"error": f"Invalid category. Choose from: {CATEGORIES}"}), 400

    # Validate price range
    try:
        if min_price is not None:
            min_price = float(min_price)
            if min_price < 0:
                return jsonify({"error": "min_price must be non-negative"}), 400
        if max_price is not None:
            max_price = float(max_price)
            if max_price < 0:
                return jsonify({"error": "max_price must be non-negative"}), 400
        if min_price is not None and max_price is not None and min_price > max_price:
            return jsonify({"error": "min_price cannot be greater than max_price"}), 400
    except ValueError:
        return jsonify({"error": "min_price and max_price must be valid numbers"}), 400

    # Validate sort_by
    valid_sort_options = ["popularity", "price_low", "price_high", "newest", "name"]
    if sort_by not in valid_sort_options:
        return jsonify({"error": f"Invalid sort_by. Choose from: {valid_sort_options}"}), 400

    logger.info(f"Fetching products: page={page}, limit={limit}, category={category}, search={search}, min_price={min_price}, max_price={max_price}, sort_by={sort_by}")

    filtered = PRODUCTS_DB

    # Filter by category
    if category:
        filtered = [p for p in filtered if p["category"].lower() == category.lower()]

    # Filter by search term
    if search:
        filtered = [p for p in filtered if search in p["name"].lower()]

    # Filter by price range
    if min_price is not None or max_price is not None:
        def get_monthly_price(product):
            pricing = product.get("pricing", {})
            # Try different price fields
            return pricing.get("monthly") or pricing.get("starting_price") or 0

        filtered = [
            p for p in filtered
            if min_price is None or get_monthly_price(p) >= min_price
        ]
        filtered = [
            p for p in filtered
            if max_price is None or get_monthly_price(p) <= max_price
        ]

    # Sort results
    if sort_by == "price_low":
        filtered.sort(key=lambda x: x.get("pricing", {}).get("monthly") or x.get("pricing", {}).get("starting_price") or 0)
    elif sort_by == "price_high":
        filtered.sort(key=lambda x: x.get("pricing", {}).get("monthly") or x.get("pricing", {}).get("starting_price") or 0, reverse=True)
    elif sort_by == "newest":
        filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    elif sort_by == "name":
        filtered.sort(key=lambda x: x.get("name", "").lower())
    else:  # popularity (default)
        filtered.sort(key=lambda x: x.get("popularity_score", 0), reverse=True)

    # Paginate
    start = (page - 1) * limit
    end = start + limit
    paginated = filtered[start:end]

    logger.info(f"Products retrieved: page={page}, limit={limit}, category={category}, search={search}, min_price={min_price}, max_price={max_price}, sort_by={sort_by}, total_results={len(filtered)}")

    return jsonify({
        "products": paginated,
        "total": len(filtered),
        "page": page,
        "pages": (len(filtered) + limit - 1) // limit,
        "filters": {
            "category": category,
            "search": search,
            "min_price": min_price,
            "max_price": max_price,
            "sort_by": sort_by
        }
    })


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    """Get a specific product by ID."""
    product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)

    if not product:
        logger.warning(f"Product lookup for non-existent ID: {product_id}")
        return jsonify({"error": "Product not found"}), 404

    # Record pricing history when product is fetched
    record_pricing_history(product_id, product.get("pricing", {}))

    logger.debug(f"Product lookup: {product_id} - {product.get('name')}")
    return jsonify(product)


@app.route("/api/products/<int:product_id>/pricing-history", methods=["GET"])
def get_pricing_history(product_id):
    """Get pricing history for a specific product.

    Query Parameters:
        start_date (str): Filter by start date (ISO8601 format)
        end_date (str): Filter by end date (ISO8601 format)
        limit (int): Maximum number of records to return (default: 100, max: 1000)

    Returns:
        JSON with pricing history and trend statistics
    """
    # Check if product exists
    product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)
    if not product:
        logger.warning(f"Pricing history lookup for non-existent product: {product_id}")
        return jsonify({"error": "Product not found"}), 404

    # Get raw history
    history = PRICING_HISTORY.get(product_id, [])

    if not history:
        # Return empty history with product info
        return jsonify({
            "product_id": product_id,
            "product_name": product.get("name"),
            "pricing_history": [],
            "trends": {
                "total_records": 0,
                "has_history": False,
            }
        })

    # Apply filters
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = min(int(request.args.get("limit", 100)), 1000)

    filtered_history = history
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            filtered_history = [
                h for h in filtered_history
                if datetime.fromisoformat(h["timestamp"].replace('Z', '+00:00')) >= start_dt
            ]
        except ValueError:
            return jsonify({"error": "Invalid start_date format. Use ISO8601."}), 400

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            filtered_history = [
                h for h in filtered_history
                if datetime.fromisoformat(h["timestamp"].replace('Z', '+00:00')) <= end_dt
            ]
        except ValueError:
            return jsonify({"error": "Invalid end_date format. Use ISO8601."}), 400

    # Apply limit
    filtered_history = filtered_history[-limit:]

    # Calculate trends
    monthly_prices = [h["monthly"] for h in filtered_history if h.get("monthly") is not None]
    annual_prices = [h["annual"] for h in filtered_history if h.get("annual") is not None]

    trends = {
        "total_records": len(filtered_history),
        "has_history": len(filtered_history) > 1,
    }

    if monthly_prices:
        trends["monthly"] = {
            "min": min(monthly_prices),
            "max": max(monthly_prices),
            "avg": round(sum(monthly_prices) / len(monthly_prices), 2),
            "latest": monthly_prices[-1],
            "first": monthly_prices[0],
            "change_percent": round(((monthly_prices[-1] - monthly_prices[0]) / monthly_prices[0] * 100) if monthly_prices[0] > 0 else 0, 2),
        }

    if annual_prices:
        trends["annual"] = {
            "min": min(annual_prices),
            "max": max(annual_prices),
            "avg": round(sum(annual_prices) / len(annual_prices), 2),
            "latest": annual_prices[-1],
            "first": annual_prices[0],
            "change_percent": round(((annual_prices[-1] - annual_prices[0]) / annual_prices[0] * 100) if annual_prices[0] > 0 else 0, 2),
        }

    logger.info(f"Pricing history lookup: product_id={product_id}, records={len(filtered_history)}")

    return jsonify({
        "product_id": product_id,
        "product_name": product.get("name"),
        "pricing_history": filtered_history,
        "trends": trends,
    })


@app.route("/api/products/batch", methods=["POST"])
def get_products_batch():
    """Get multiple products by IDs in a single request.

    Request Body:
        product_ids (list): List of product IDs to retrieve

    Returns:
        JSON with found products and list of not found IDs
    """
    data = request.get_json()

    if not data or "product_ids" not in data:
        logger.warning("Batch product lookup missing product_ids")
        return jsonify({"error": "product_ids array is required"}), 400

    product_ids = data["product_ids"]

    if not isinstance(product_ids, list):
        logger.warning("Batch product lookup invalid product_ids type")
        return jsonify({"error": "product_ids must be an array"}), 400

    if len(product_ids) > 100:
        logger.warning(f"Batch product lookup exceeds limit: {len(product_ids)}")
        return jsonify({"error": "Maximum 100 product IDs allowed per request"}), 400

    found_products = []
    not_found_ids = []

    for product_id in product_ids:
        product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)
        if product:
            found_products.append(product)
            # Record pricing history for each product
            record_pricing_history(product_id, product.get("pricing", {}))
        else:
            not_found_ids.append(product_id)

    logger.info(f"Batch lookup: {len(found_products)} found, {len(not_found_ids)} not found")

    return jsonify({
        "products": found_products,
        "not_found": not_found_ids,
        "total": len(found_products),
        "requested": len(product_ids)
    })


@app.route("/api/products/featured", methods=["GET"])
def get_featured_products():
    """Get featured/popular products with additional metadata.

    Query Parameters:
        sort (str): Sort by 'popularity', 'price_low', 'price_high', 'newest' (default: 'popularity')
        limit (int): Number of products to return (default: 10, max: 50)
        category (str): Filter by category (optional)
    """
    sort_by = request.args.get("sort", "popularity")
    limit = min(int(request.args.get("limit", 10)), 50)
    category = request.args.get("category", None)

    # Get featured product names (simulated popularity based on market presence)
    featured_names = ["Slack", "Notion", "Zoom", "Shopify", "HubSpot", "Stripe", "Salesforce", "Figma", "Airtable", "Zendesk",
                     "Intercom", "Asana", "Trello", "Monday.com", "ClickUp", "Dropbox", "Mailchimp", "Freshdesk", "Pipedrive", "Canva"]

    # Build product list with simulated metrics
    products = []
    for idx, name in enumerate(featured_names):
        product = next((p for p in PRODUCTS_DB if p.get("name", "").lower() == name.lower()), None)
        if product:
            # Add simulated popularity score
            product = dict(product)
            product["popularity_score"] = 100 - idx * 3
            product["monthly_searches"] = (100 - idx * 3) * 1000
            if category is None or product.get("category") == category:
                products.append(product)

    # Sort based on requested criteria
    if sort_by == "price_low":
        products.sort(key=lambda x: x.get("pricing", {}).get("monthly", 0))
    elif sort_by == "price_high":
        products.sort(key=lambda x: x.get("pricing", {}).get("monthly", 0), reverse=True)
    elif sort_by == "newest":
        products.sort(key=lambda x: x.get("popularity_score", 0), reverse=True)
    else:  # popularity (default)
        products.sort(key=lambda x: x.get("popularity_score", 0), reverse=True)

    return jsonify({
        "count": len(products[:limit]),
        "products": products[:limit],
        "sort": sort_by,
        "total_featured": len(products)
    })


@app.route("/api/products/export", methods=["GET"])
def export_products():
    """Export products as CSV or JSON.

    Query Parameters:
        format (str): 'csv' or 'json' (default: 'json')
        category (str): Filter by category name (optional)
        limit (int): Max products to export (default: 100, max: 1000)
    """
    try:
        export_format = request.args.get("format", "json").lower()
        category = request.args.get("category")
        limit = min(int(request.args.get("limit", 100)), 1000)

        if export_format not in ("csv", "json"):
            return jsonify({"error": "Format must be 'csv' or 'json'"}), 400

        # Filter products
        products = PRODUCTS_DB
        if category:
            products = [p for p in products if p.get("category", "").lower() == category.lower()]

        products = products[:limit]

        if export_format == "csv":
            # Generate CSV
            if not products:
                return jsonify({"error": "No products found"}), 404

            # CSV header
            csv_lines = ["id,name,category,price,features,competitors"]

            for p in products:
                name = p.get("name", "").replace(",", ";")
                cat = p.get("category", "").replace(",", ";")
                feats = ";".join(p.get("features", []))
                comps = ";".join(p.get("competitors", []))
                price = p.get("price", 0)
                csv_lines.append(f'{p.get("id")},{name},{cat},{price},{feats},{comps}')

            csv_content = "\n".join(csv_lines)

            return csv_content, 200, {
                "Content-Type": "text/csv",
                "Content-Disposition": "attachment; filename=products.csv"
            }
        else:
            # JSON format
            return jsonify({
                "count": len(products),
                "products": products
            })

    except Exception as e:
        logger.exception(f"Export failed: {str(e)}")
        return jsonify({"error": "Export failed", "message": str(e)}), 500


@app.route("/api/pricing/analyze", methods=["POST"])
@require_api_key
def analyze_pricing():
    """Analyze pricing for a product and get recommendations.

    Request Body (JSON):
        product_name (str): Name of the product (default: "My Product")
        current_price (float): Current monthly price (default: 99.0)
        competitors (list): List of competitor names (default: ["competitor_a"])
        customer_segment (str): Target segment - smb, startup, or enterprise (default: "smb")
        features (list): List of product features (default: ["api_access", "analytics"])
    """
    data = request.get_json()

    if not data:
        logger.warning("Pricing analysis failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    # Extract request parameters with validation
    product_name = data.get("product_name", "My Product")

    # Validate product_name
    if not isinstance(product_name, str) or not product_name.strip():
        logger.warning("Invalid product_name provided")
        return jsonify({"error": "product_name must be a non-empty string"}), 400

    # Validate current_price
    try:
        current_price = float(data.get("current_price", 99.0))
        if current_price < 0:
            logger.warning(f"Negative current_price provided: {current_price}")
            return jsonify({"error": "current_price must be non-negative"}), 400
    except (TypeError, ValueError) as e:
        logger.warning(f"Pricing analysis failed: Invalid price value: {data.get('current_price')}")
        return jsonify({"error": f"Invalid current_price: {str(e)}"}), 400

    competitors = data.get("competitors", ["competitor_a"])
    if not isinstance(competitors, list):
        logger.warning("Invalid competitors type provided")
        return jsonify({"error": "competitors must be a list"}), 400

    customer_segment = data.get("customer_segment", "smb")
    if customer_segment not in ["smb", "startup", "enterprise"]:
        logger.warning(f"Invalid customer_segment: {customer_segment}")
        return jsonify({"error": "customer_segment must be one of: smb, startup, enterprise"}), 400

    features = data.get("features", ["api_access", "analytics"])
    if not isinstance(features, list):
        logger.warning("Invalid features type provided")
        return jsonify({"error": "features must be a list"}), 400

    logger.info(f"Analyzing pricing for product: {product_name}, segment: {customer_segment}")

    # Validate customer_segment
    valid_segments = ["startup", "smb", "enterprise"]
    if customer_segment not in valid_segments:
        logger.warning(f"Pricing analysis failed: Invalid customer_segment: {customer_segment}")
        return jsonify({"error": f"Invalid customer_segment. Choose from: {valid_segments}"}), 400

    logger.info(f"Pricing analysis requested: product={product_name}, segment={customer_segment}, price=${current_price}")

    # Create pricing request
    pricing_request = PricingRequest(
        product_name=product_name,
        current_price=current_price,
        competitors=competitors,
        customer_segment=customer_segment,
        features=features
    )

    # Get recommendation
    recommendation = pricing_engine.analyze(pricing_request)

    # Get additional analysis (price elasticity and charm pricing)
    # Determine market category from product
    market_category = "default"
    name_lower = product_name.lower()
    comps_lower = " ".join(c.lower() for c in competitors)
    combined = f" {name_lower} {comps_lower} "

    # Map to market categories
    if any(term in combined for term in ["crm", "sales", "salesforce"]):
        market_category = "crm"
    elif any(term in combined for term in ["analytics", "mixpanel", "amplitude"]):
        market_category = "analytics"
    elif any(term in combined for term in ["marketing", "mailchimp", "hubspot"]):
        market_category = "marketing"
    elif any(term in combined for term in ["project", "asana", "monday", "trello"]):
        market_category = "project_management"
    elif any(term in combined for term in ["help", "support", "zendesk", "freshdesk"]):
        market_category = "helpdesk"

    # Get price elasticity analysis
    elasticity_analysis = calculate_price_elasticity(
        current_price=current_price,
        customer_segment=customer_segment,
        market_category=market_category
    )

    # Get charm pricing analysis
    charm_analysis = calculate_charm_pricing(
        base_price=recommendation.recommended_price,
        strategy="classic"
    )

    return jsonify({
        "product_name": recommendation.product_name,
        "recommended_price": recommendation.recommended_price,
        "confidence": recommendation.confidence,
        "price_change_percent": recommendation.price_change_percent,
        "mrr_projection": recommendation.mrr_projection,
        "key_factors": recommendation.key_factors,
        "competitor_positioning": recommendation.competitor_positioning,
        # Added advanced analysis
        "price_elasticity": {
            "elasticity_coefficient": elasticity_analysis["elasticity_coefficient"],
            "elasticity_type": elasticity_analysis["elasticity_type"],
            "optimal_price": elasticity_analysis["optimal_price"],
            "optimal_price_change_pct": elasticity_analysis["optimal_price_change_pct"],
            "potential_revenue_gain_pct": elasticity_analysis["potential_revenue_gain_pct"],
            "description": elasticity_analysis["description"],
        },
        "charm_pricing": {
            "best_charm_price": charm_analysis["best_charm_price"],
            "best_adjustment": charm_analysis["best_adjustment"],
            "conversion_uplift_estimate": charm_analysis["conversion_uplift_estimate"],
            "strategy_name": charm_analysis["strategy_name"],
        }
    })


@app.route("/api/pricing/batch-analyze", methods=["POST"])
@require_api_key
def batch_analyze_pricing():
    """Analyze pricing for multiple products at once.

    Request Body (JSON):
        products (list): List of product analysis requests.
            Each product should have:
            - product_name (str): Name of the product
            - current_price (float): Current monthly price
            - competitors (list): List of competitor names
            - customer_segment (str): Target segment - smb, startup, or enterprise
            - features (list): List of product features

    Example:
        {
            "products": [
                {"product_name": "Product A", "current_price": 99, "competitors": ["Comp1"], "customer_segment": "smb", "features": ["api"]},
                {"product_name": "Product B", "current_price": 149, "competitors": ["Comp2"], "customer_segment": "enterprise", "features": ["api", "analytics"]}
            ]
        }
    """
    data = request.get_json()

    if not data:
        logger.warning("Batch pricing analysis failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    products = data.get("products", [])

    if not products:
        return jsonify({"error": "products array is required"}), 400

    if len(products) > 20:
        return jsonify({"error": "Maximum 20 products per batch request"}), 400

    results = []
    errors = []

    for idx, product in enumerate(products):
        try:
            product_name = product.get("product_name", f"Product {idx + 1}")
            current_price = float(product.get("current_price", 99.0))
            competitors = product.get("competitors", [])
            customer_segment = product.get("customer_segment", "smb")
            features = product.get("features", [])

            # Validate segment
            if customer_segment not in ["smb", "startup", "enterprise"]:
                errors.append({"index": idx, "error": f"Invalid customer_segment: {customer_segment}"})
                continue

            pricing_request = PricingRequest(
                product_name=product_name,
                current_price=current_price,
                competitors=competitors,
                customer_segment=customer_segment,
                features=features
            )

            recommendation = pricing_engine.analyze(pricing_request)

            results.append({
                "product_name": recommendation.product_name,
                "recommended_price": recommendation.recommended_price,
                "confidence": recommendation.confidence,
                "price_change_percent": recommendation.price_change_percent,
                "mrr_projection": recommendation.mrr_projection,
                "key_factors": recommendation.key_factors,
                "competitor_positioning": recommendation.competitor_positioning
            })

        except Exception as e:
            logger.warning(f"Batch analysis error at index {idx}: {str(e)}")
            errors.append({"index": idx, "error": str(e)})

    return jsonify({
        "results": results,
        "errors": errors,
        "total_analyzed": len(results),
        "total_requested": len(products)
    })


@app.route("/api/pricing/tiers", methods=["GET"])
def get_pricing_tiers():
    """Get available pricing tiers."""
    return jsonify({
        "tiers": [
            {
                "name": "Starter",
                "monthly_price": 49,
                "api_calls_per_month": 100,
                "features": ["basic_analytics", "email_support", "100 API calls/month"]
            },
            {
                "name": "Growth",
                "monthly_price": 199,
                "api_calls_per_month": 1000,
                "features": ["advanced_analytics", "competitor_tracking", "priority_support", "1,000 API calls/month"]
            },
            {
                "name": "Enterprise",
                "monthly_price": 999,
                "api_calls_per_month": -1,  # unlimited
                "features": ["custom_models", "dedicated_support", "SLA", "Unlimited API calls"]
            }
        ]
    })


@app.route("/api/pricing/discount-plan", methods=["POST"])
@require_api_key
def plan_discount():
    """Plan optimal discount strategy for a product.

    Request Body (JSON):
        product_name (str): Name of the product
        base_price (float): Current monthly price
        discount_type (str): Type of discount - seasonal, promotion, volume, or loyalty
        duration_days (int): Duration of the discount in days (default: 30)
        target_customer_segment (str): Target segment - smb, startup, or enterprise

    Returns optimal discount percentage and expected revenue impact.
    """
    data = request.get_json()

    if not data:
        logger.warning("Discount planning failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    product_name = data.get("product_name", "My Product")

    if not isinstance(product_name, str) or not product_name.strip():
        logger.warning("Invalid product_name provided for discount planning")
        return jsonify({"error": "product_name must be a non-empty string"}), 400

    try:
        base_price = float(data.get("base_price", 99.0))
        if base_price <= 0:
            logger.warning(f"Invalid base_price for discount planning: {base_price}")
            return jsonify({"error": "base_price must be positive"}), 400
    except (TypeError, ValueError) as e:
        logger.warning(f"Invalid base_price value: {data.get('base_price')}")
        return jsonify({"error": f"Invalid base_price: {str(e)}"}), 400

    discount_type = data.get("discount_type", "seasonal")
    valid_discount_types = ["seasonal", "promotion", "volume", "loyalty", "early_bird"]
    if discount_type not in valid_discount_types:
        logger.warning(f"Invalid discount_type: {discount_type}")
        return jsonify({"error": f"discount_type must be one of: {valid_discount_types}"}), 400

    try:
        duration_days = int(data.get("duration_days", 30))
        if duration_days < 1 or duration_days > 365:
            logger.warning(f"Invalid duration_days: {duration_days}")
            return jsonify({"error": "duration_days must be between 1 and 365"}), 400
    except (TypeError, ValueError):
        logger.warning(f"Invalid duration_days: {data.get('duration_days')}")
        return jsonify({"error": "duration_days must be an integer"}), 400

    customer_segment = data.get("target_customer_segment", "smb")
    valid_segments = ["smb", "startup", "enterprise"]
    if customer_segment not in valid_segments:
        logger.warning(f"Invalid customer_segment: {customer_segment}")
        return jsonify({"error": f"customer_segment must be one of: {valid_segments}"}), 400

    logger.info(f"Planning discount for {product_name}: type={discount_type}, duration={duration_days} days")

    # Calculate optimal discount based on type and segment
    discount_config = {
        "seasonal": {
            "smb": {"optimal_discount": 0.20, "min_discount": 0.10, "max_discount": 0.30},
            "startup": {"optimal_discount": 0.25, "min_discount": 0.15, "max_discount": 0.35},
            "enterprise": {"optimal_discount": 0.15, "min_discount": 0.10, "max_discount": 0.25}
        },
        "promotion": {
            "smb": {"optimal_discount": 0.25, "min_discount": 0.15, "max_discount": 0.40},
            "startup": {"optimal_discount": 0.30, "min_discount": 0.20, "max_discount": 0.45},
            "enterprise": {"optimal_discount": 0.20, "min_discount": 0.10, "max_discount": 0.30}
        },
        "volume": {
            "smb": {"optimal_discount": 0.15, "min_discount": 0.05, "max_discount": 0.25},
            "startup": {"optimal_discount": 0.20, "min_discount": 0.10, "max_discount": 0.30},
            "enterprise": {"optimal_discount": 0.25, "min_discount": 0.15, "max_discount": 0.40}
        },
        "loyalty": {
            "smb": {"optimal_discount": 0.10, "min_discount": 0.05, "max_discount": 0.20},
            "startup": {"optimal_discount": 0.15, "min_discount": 0.10, "max_discount": 0.25},
            "enterprise": {"optimal_discount": 0.20, "min_discount": 0.10, "max_discount": 0.30}
        },
        "early_bird": {
            "smb": {"optimal_discount": 0.30, "min_discount": 0.20, "max_discount": 0.40},
            "startup": {"optimal_discount": 0.35, "min_discount": 0.25, "max_discount": 0.50},
            "enterprise": {"optimal_discount": 0.25, "min_discount": 0.15, "max_discount": 0.35}
        }
    }

    config = discount_config[discount_type][customer_segment]
    optimal_discount = config["optimal_discount"]
    min_discount = config["min_discount"]
    max_discount = config["max_discount"]

    # Calculate pricing
    discounted_price = base_price * (1 - optimal_discount)
    discount_amount = base_price * optimal_discount

    # Estimate customer acquisition impact
    acquisition_multiplier = 1.0 + (optimal_discount * 2.5)  # Higher discount = more customers
    churn_reduction = optimal_discount * 0.3  # Discounts reduce churn

    # Calculate revenue projection
    # Assume 100 customers at base price, then apply discount impact
    assumed_customers = 100
    original_revenue = base_price * assumed_customers * (duration_days / 30)
    discounted_revenue = discounted_price * assumed_customers * acquisition_multiplier * (duration_days / 30)

    revenue_change_pct = ((discounted_revenue - original_revenue) / original_revenue) * 100 if original_revenue > 0 else 0

    # ROI calculation
    roi = (discounted_revenue - original_revenue) / (original_revenue * optimal_discount) if optimal_discount > 0 else 0

    return jsonify({
        "product_name": product_name,
        "base_price": base_price,
        "discount_type": discount_type,
        "duration_days": duration_days,
        "target_segment": customer_segment,
        "optimal_discount_percent": optimal_discount * 100,
        "discounted_price": round(discounted_price, 2),
        "discount_amount": round(discount_amount, 2),
        "price_tiers": [
            {"discount_percent": min_discount * 100, "price": round(base_price * (1 - min_discount), 2), "strategy": "conservative"},
            {"discount_percent": optimal_discount * 100, "price": round(discounted_price, 2), "strategy": "recommended"},
            {"discount_percent": max_discount * 100, "price": round(base_price * (1 - max_discount), 2), "strategy": "aggressive"}
        ],
        "projections": {
            "expected_acquisition_lift": f"+{int((acquisition_multiplier - 1) * 100)}%",
            "churn_reduction": f"-{int(churn_reduction * 100)}%",
            "estimated_revenue": round(discounted_revenue, 2),
            "revenue_vs_full_price": f"{'+' if revenue_change_pct > 0 else ''}{round(revenue_change_pct, 1)}%",
            "roi_multiplier": round(roi, 2) if roi > 0 else 0
        },
        "recommendations": [
            f"Run {discount_type} discount for {duration_days} days targeting {customer_segment} segment",
            f"Offer {int(optimal_discount * 100)}% off (${round(discount_amount, 2)}/month savings)",
            f"Expect ~{int((acquisition_multiplier - 1) * 100)}% increase in customer acquisition",
            "Track conversion rates and adjust discount depth if needed"
        ]
    })


@app.route("/api/categories", methods=["GET"])
def get_categories():
    """Get all available categories."""
    categories = list(set(p["category"] for p in PRODUCTS_DB))
    return jsonify({"categories": sorted(categories)})


@app.route("/api/trends", methods=["GET"])
def get_pricing_trends():
    """Get pricing trends (simulated)."""
    return jsonify({
        "trends": [
            {"category": "Communication", "avg_price_change": 5.2, "trend": "up"},
            {"category": "Productivity", "avg_price_change": 3.1, "trend": "up"},
            {"category": "Design", "avg_price_change": 8.7, "trend": "up"},
            {"category": "CRM", "avg_price_change": -2.3, "trend": "down"},
            {"category": "Project Management", "avg_price_change": 4.5, "trend": "up"},
        ]
    })


@app.route("/api/price-history/<int:product_id>", methods=["GET"])
def get_price_history(product_id):
    """Get historical pricing data for a product with trend analysis.

    Returns simulated monthly price history for the past 12 months with trend analysis.

    Query Parameters:
        include_trend (bool): Include trend analysis (default true)

    Response:
        product_id (int): Product ID
        product_name (str): Product name
        history (list): List of monthly price data
        data_points (int): Number of data points
        trend_analysis (dict): Trend detection and forecast (if requested)
    """
    # Check if trend analysis is requested
    include_trend = request.args.get("include_trend", "true").lower() == "true"

    # Find product in database
    product = next((p for p in PRODUCTS_DB if p.get("id") == product_id), None)

    if not product:
        # Generate simulated historical data for unknown products
        base_price = random.uniform(10, 150)
    else:
        base_price = product.get("pricing", {}).get("monthly", 50)

    # Generate 12 months of simulated historical data
    history = []
    import datetime
    current_date = datetime.datetime.now()

    for i in range(12):
        month_date = current_date - datetime.timedelta(days=30 * (11 - i))
        # Add some random variation to simulate price changes
        variation = random.uniform(-0.15, 0.15)
        price = round(base_price * (1 + variation), 2)
        history.append({
            "date": month_date.strftime("%Y-%m"),
            "monthly_price": price,
            "annual_price": round(price * 10, 2),  # Rough annual estimate
            "change_percent": round(variation * 100, 2)
        })

    # Extract prices for trend analysis
    prices = [h["monthly_price"] for h in history]

    # Build response
    response = {
        "product_id": product_id,
        "product_name": product.get("name") if product else f"Product {product_id}",
        "history": history,
        "data_points": len(history)
    }

    # Add trend analysis if requested
    if include_trend:
        trend_analysis = detect_price_trends(prices, periods=3)
        response["trend_analysis"] = trend_analysis

    return jsonify(response)


@app.route("/api/competitors/<product_name>", methods=["GET"])
@require_api_key
def get_competitors(product_name):
    """Get competitors for a product (simulated).

    Query Parameters:
        None

    Response:
        product (str): Product name
        competitors (list): List of competitor objects with name and monthly_price
    """
    # In production, this would analyze real competitor data
    competitors = [
        {"name": f"Competitor A", "monthly_price": round(random.uniform(29, 199), 2)},
        {"name": f"Competitor B", "monthly_price": round(random.uniform(39, 249), 2)},
        {"name": f"Competitor C", "monthly_price": round(random.uniform(19, 179), 2)},
    ]
    return jsonify({
        "product": product_name,
        "competitors": competitors
    })


@app.route("/api/categorize", methods=["POST"])
def categorize_product():
    """Categorize a product using NLP-based analysis.

    Request Body (JSON):
        product_name (str): Name of the product (required)
        competitors (list): List of competitor product names (optional)
        features (list): List of product features (optional)

    Response:
        primary_category (str): Primary category identifier
        category_name (str): Human-readable category name
        confidence (float): Confidence score (0-1)
        alternatives (list): Alternative categories with confidence scores
        method (str): Method used for categorization
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    product_name = data.get("product_name")
    if not product_name:
        return jsonify({"error": "product_name is required"}), 400

    competitors = data.get("competitors", [])
    features = data.get("features", [])

    result = categorize_product_nlp(product_name, competitors, features)

    return jsonify(result)


@app.route("/api/trends/analyze", methods=["POST"])
def analyze_trends():
    """Analyze price trends and forecast future prices.

    Request Body (JSON):
        historical_prices (list): List of historical prices (required, min 3 values)
        periods (int): Number of periods to forecast (optional, default 6)

    Response:
        trend (str): Overall trend classification
        trend_direction (str): Direction of trend (increasing/decreasing/stable)
        trend_strength (str): Strength of trend (strong/moderate/weak)
        slope (float): Linear regression slope
        r_squared (float): Coefficient of determination
        volatility (float): Standard deviation of price changes
        average_price (float): Average historical price
        price_change_total (float): Total price change over period
        price_change_pct (float): Percentage price change
        forecast (list): Predicted future prices
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    historical_prices = data.get("historical_prices", [])
    if len(historical_prices) < 3:
        return jsonify({
            "error": "At least 3 historical price data points are required"
        }), 400

    periods = data.get("periods", 6)

    result = detect_price_trends(historical_prices, periods)

    return jsonify(result)


@app.route("/api/competitors/analyze", methods=["POST"])
def analyze_competitors():
    """Analyze competitor pricing and positioning.

    Request Body (JSON):
        product_name (str): Name of your product (required)
        product_price (float): Your current price (required)
        competitor_prices (list): List of competitor prices (required)

    Response:
        positioning (str): Your market positioning
        percentile (float): Your price percentile among competitors
        your_price (float): Your current price
        competitor_stats (dict): Statistics about competitor prices
        price_gap_to_lowest (float): Gap to lowest competitor
        price_gap_to_highest (float): Gap to highest competitor
        market_pressure (int): Market pressure score (0-100)
        recommendation (str): Strategic recommendation
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    product_name = data.get("product_name")
    product_price = data.get("product_price")
    competitor_prices = data.get("competitor_prices", [])

    if not product_name:
        return jsonify({"error": "product_name is required"}), 400

    if product_price is None:
        return jsonify({"error": "product_price is required"}), 400

    if not competitor_prices:
        return jsonify({"error": "competitor_prices is required and must not be empty"}), 400

    result = analyze_competitor_pricing(product_name, product_price, competitor_prices)

    return jsonify(result)


@app.route("/api/demo/request", methods=["POST"])
def submit_demo_request():
    """Handle demo request form submissions from landing page.

    Request Body (JSON):
        email (str): User's email address (required)
        name (str): User's name (optional)
        company (str): Company name (optional)
    """
    data = request.get_json()

    if not data:
        logger.warning("Demo request failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    email = data.get("email")
    if not email:
        logger.warning("Demo request failed: Email is required")
        return jsonify({"error": "Email is required"}), 400

    # Validate email format
    if not validate_email(email):
        logger.warning(f"Demo request failed: Invalid email format: {email}")
        return jsonify({"error": "Invalid email format"}), 400

    logger.info(f"New demo request received for email: {email[:3]}***")  # Log partially masked email

    # Generate a request ID
    request_id = f"demo_{int(time.time())}_{random.randint(1000, 9999)}"

    logger.info(f"Demo request received: {email} (request_id: {request_id})")

    # In production, this would:
    # 1. Store the lead in a database
    # 2. Send a confirmation email
    # 3. Trigger a CRM webhook

    # For now, create an API key automatically
    api_key = f"spk_{secrets.token_urlsafe(32)}"
    API_KEYS[api_key] = {
        "tier": "starter",
        "calls": 0,
        "created": time.time(),
        "last_used": None,
        "email": email,
        "demo_request_id": request_id,
    }

    logger.info(f"Demo request created: {request_id}, email: {email}")
    return jsonify({
        "success": True,
        "request_id": request_id,
        "api_key": api_key,
        "message": "Demo request received. Your API key is ready!"
    }), 201


# Price alert storage (in production, use a database)
# Format: {alert_id: {"product_id": int, "target_price": float, "webhook_url": str, "created": timestamp}}
PRICE_ALERTS: dict[str, dict[str, Any]] = {}

# Competitor tracking storage
# Format: {product_id: [{"competitor": str, "price": float, "recorded_at": timestamp}]}
COMPETITOR_HISTORY: dict[int, list[dict[str, Any]]] = {}

# Initialize competitor history with some sample data
for product in PRODUCTS_DB[:10]:
    COMPETITOR_HISTORY[product["id"]] = [
        {"competitor": "Competitor A", "price": product["pricing"]["monthly"] * random.uniform(0.8, 1.2), "recorded_at": time.time() - 86400},
        {"competitor": "Competitor B", "price": product["pricing"]["monthly"] * random.uniform(0.7, 1.3), "recorded_at": time.time() - 172800},
    ]


@app.route("/api/alerts", methods=["POST"])
@require_api_key
def create_price_alert():
    """Create a price alert that triggers a webhook when price changes.

    Request Body (JSON):
        product_id (int): ID of the product to track (required)
        target_price (float): Target price to trigger alert (required)
        webhook_url (str): URL to call when price threshold is hit (required)
    """
    data = request.get_json()

    if not data:
        logger.warning("Price alert request with no data")
        return jsonify({"error": "No data provided"}), 400

    product_id = data.get("product_id")
    target_price = data.get("target_price")
    webhook_url = data.get("webhook_url")

    if not product_id or not target_price or not webhook_url:
        logger.warning("Price alert request with missing required fields")
        return jsonify({"error": "product_id, target_price, and webhook_url are required"}), 400

    # Validate webhook_url format (basic check)
    if not isinstance(webhook_url, str) or not webhook_url.startswith(("http://", "https://")):
        logger.warning(f"Invalid webhook_url format: {webhook_url}")
        return jsonify({"error": "webhook_url must be a valid HTTP/HTTPS URL"}), 400

    # Validate target_price is a positive number
    try:
        target_price = float(target_price)
        if target_price <= 0:
            raise ValueError("Price must be positive")
    except (ValueError, TypeError):
        logger.warning(f"Invalid target_price: {target_price}")
        return jsonify({"error": "target_price must be a positive number"}), 400

    # Verify product exists
    product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)
    if not product:
        logger.warning(f"Price alert for non-existent product: {product_id}")
        return jsonify({"error": "Product not found"}), 404

    # Generate alert ID
    alert_id = f"alert_{secrets.token_urlsafe(8)}"

    PRICE_ALERTS[alert_id] = {
        "product_id": product_id,
        "product_name": product["name"],
        "target_price": target_price,
        "webhook_url": webhook_url,
        "created": time.time(),
        "triggered": False
    }

    logger.info(f"Price alert created: {alert_id} for product {product_id}")
    return jsonify({
        "success": True,
        "alert_id": alert_id,
        "message": f"Price alert created for {product['name']} at ${target_price}"
    }), 201


@app.route("/api/alerts", methods=["GET"])
@require_api_key
def list_price_alerts():
    """List all price alerts for the current user."""
    return jsonify({
        "alerts": [
            {
                "alert_id": alert_id,
                "product_name": alert["product_name"],
                "target_price": alert["target_price"],
                "webhook_url": alert["webhook_url"],
                "created": alert["created"],
                "triggered": alert["triggered"]
            }
            for alert_id, alert in PRICE_ALERTS.items()
        ]
    })


@app.route("/api/alerts/<alert_id>", methods=["DELETE"])
@require_api_key
def delete_price_alert(alert_id):
    """Delete a price alert."""
    if alert_id not in PRICE_ALERTS:
        return jsonify({"error": "Alert not found"}), 404

    del PRICE_ALERTS[alert_id]
    return jsonify({"success": True, "message": "Alert deleted"})


@app.route("/api/competitors/track", methods=["POST"])
@require_api_key
def track_competitor():
    """Add a competitor price to tracking history."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    product_id = data.get("product_id")
    competitor_name = data.get("competitor_name")
    competitor_price = data.get("competitor_price")

    if not product_id or not competitor_name or not competitor_price:
        return jsonify({"error": "product_id, competitor_name, and competitor_price are required"}), 400

    # Verify product exists
    product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    # Add to history
    if product_id not in COMPETITOR_HISTORY:
        COMPETITOR_HISTORY[product_id] = []

    COMPETITOR_HISTORY[product_id].append({
        "competitor": competitor_name,
        "price": competitor_price,
        "recorded_at": time.time()
    })

    return jsonify({
        "success": True,
        "message": f"Tracked {competitor_name} at ${competitor_price} for {product['name']}"
    })


@app.route("/api/competitors/history/<int:product_id>", methods=["GET"])
@require_api_key
def get_competitor_history(product_id):
    """Get competitor price history for a product."""
    # Verify product exists
    product = next((p for p in PRODUCTS_DB if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    history = COMPETITOR_HISTORY.get(product_id, [])

    # Also include current competitor prices
    competitors = [
        {"name": f"Competitor A", "monthly_price": product["pricing"]["monthly"] * random.uniform(0.8, 1.2)},
        {"name": f"Competitor B", "monthly_price": product["pricing"]["monthly"] * random.uniform(0.7, 1.3)},
        {"name": f"Competitor C", "monthly_price": product["pricing"]["monthly"] * random.uniform(0.9, 1.1)},
    ]

    return jsonify({
        "product": product["name"],
        "current_competitors": competitors,
        "price_history": history
    })


@app.route("/api/competitors/enrich", methods=["POST"])
@require_api_key
def enrich_competitor_data():
    """Enrich competitor data from G2 and Capterra.

    Request Body:
        {
            "product_name": "Salesforce",
            "competitors": ["HubSpot", "Zoho", "Pipedrive"],
            "sources": ["g2", "capterra"]  // optional, defaults to both
        }

    Returns enriched competitor data including ratings, pricing tiers, and reviews.
    """
    data = request.get_json() or {}

    product_name = data.get("product_name", "")
    competitors = data.get("competitors", [])
    sources = data.get("sources")  # optional, defaults to ["g2", "capterra"]

    if not product_name:
        return jsonify({"error": "product_name is required"}), 400

    if not competitors:
        return jsonify({"error": "competitors array is required"}), 400

    result = get_competitor_enrichment(product_name, competitors, sources)

    return jsonify(result)


@app.route("/api/competitors/pricing/<competitor_name>", methods=["GET"])
def get_competitor_pricing(competitor_name):
    """Get aggregated pricing data for a competitor from G2 and Capterra.

    Returns pricing tiers, ratings, and value scores from multiple sources.
    """
    if not competitor_name:
        return jsonify({"error": "competitor_name is required"}), 400

    result = get_aggregated_competitor_pricing(competitor_name)

    return jsonify(result)


@app.route("/api/competitors/sources", methods=["GET"])
def list_competitor_sources():
    """List available competitor data sources."""
    return jsonify({
        "sources": [
            {
                "id": "g2",
                "name": "G2",
                "description": "G2 provides B2B software reviews, ratings, and pricing comparisons",
                "data_types": ["ratings", "review_count", "pricing_tiers", "competitors_compared"],
            },
            {
                "id": "capterra",
                "name": "Capterra",
                "description": "Capterra provides software reviews, comparisons, and user ratings",
                "data_types": ["ratings", "ease_of_use", "customer_service", "features", "value_for_money"],
            },
        ],
        "note": "Data is simulated for demonstration. In production, APIs would provide real-time data."
    })


@app.route("/api/products/bulk", methods=["POST"])
@require_api_key
def bulk_lookup_products():
    """Look up multiple products at once."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    product_ids = data.get("product_ids", [])

    if not product_ids:
        return jsonify({"error": "product_ids array is required"}), 400

    if len(product_ids) > 50:
        return jsonify({"error": "Maximum 50 products per request"}), 400

    results = []
    not_found = []

    for pid in product_ids:
        product = next((p for p in PRODUCTS_DB if p["id"] == pid), None)
        if product:
            results.append(product)
        else:
            not_found.append(pid)

    return jsonify({
        "products": results,
        "not_found": not_found,
        "total": len(results),
        "requested": len(product_ids)
    })


@app.route("/api/products/bulk/search", methods=["POST"])
@require_api_key
def bulk_search_products():
    """Search for multiple products by name (bulk lookup by names)."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    search_terms = data.get("search_terms", [])

    if not search_terms:
        return jsonify({"error": "search_terms array is required"}), 400

    if len(search_terms) > 20:
        return jsonify({"error": "Maximum 20 search terms per request"}), 400

    results = []
    for term in search_terms:
        term_lower = term.lower()
        matching = [p for p in PRODUCTS_DB if term_lower in p["name"].lower()]
        results.append({
            "search_term": term,
            "matches": matching
        })

    return jsonify({
        "results": results
    })


@app.route("/api/market/report", methods=["GET"])
@app.route("/api/market-report", methods=["GET"])
def get_market_report():
    """Get comprehensive market report with pricing insights across categories."""
    # Import benchmarks for market data
    from src.benchmarks import INDUSTRY_BENCHMARKS

    # Calculate aggregate statistics
    total_categories = len(INDUSTRY_BENCHMARKS)
    avg_price = sum(b["avg_price"] for b in INDUSTRY_BENCHMARKS.values()) / total_categories
    avg_mrr = sum(b["median_mrr"] for b in INDUSTRY_BENCHMARKS.values()) / total_categories
    avg_discount = sum(b["typical_discount"] for b in INDUSTRY_BENCHMARKS.values()) / total_categories

    # Find highest and lowest price categories
    sorted_by_price = sorted(INDUSTRY_BENCHMARKS.items(), key=lambda x: x[1]["avg_price"], reverse=True)
    highest_price = sorted_by_price[0]
    lowest_price = sorted_by_price[-1]

    # Find highest MRR categories
    sorted_by_mrr = sorted(INDUSTRY_BENCHMARKS.items(), key=lambda x: x[1]["median_mrr"], reverse=True)

    # Build category insights
    category_insights = []
    for category, data in INDUSTRY_BENCHMARKS.items():
        category_insights.append({
            "category": category,
            "name": data["name"],
            "avg_price": data["avg_price"],
            "price_range": f"${data['price_range_low']:.2f} - ${data['price_range_high']:.2f}",
            "median_mrr": data["median_mrr"],
            "typical_discount": f"{data['typical_discount']*100:.0f}%",
            "position": "premium" if data["avg_price"] > avg_price * 1.2 else "mid-market" if data["avg_price"] > avg_price * 0.8 else "value"
        })

    # Market trends (simulated based on category positions)
    trends = []
    for category, data in INDUSTRY_BENCHMARKS.items():
        if data["avg_price"] > 100:
            trends.append({"category": category, "trend": "stable", "growth": "+2-5%"})
        elif data["avg_price"] > 50:
            trends.append({"category": category, "trend": "growing", "growth": "+5-10%"})
        else:
            trends.append({"category": category, "trend": "competitive", "growth": "+3-7%"})

    return jsonify({
        "market_summary": {
            "total_categories": total_categories,
            "average_price": round(avg_price, 2),
            "average_median_mrr": round(avg_mrr, 2),
            "average_discount": f"{avg_discount*100:.1f}%",
            "total_products_indexed": len(PRODUCTS_DB),
            "generated_at": datetime.now(timezone.utc).isoformat()
        },
        "price_segments": {
            "premium": {
                "description": "Above market average",
                "categories": [c["category"] for c in category_insights if c["position"] == "premium"]
            },
            "mid_market": {
                "description": "At market average",
                "categories": [c["category"] for c in category_insights if c["position"] == "mid-market"]
            },
            "value": {
                "description": "Below market average",
                "categories": [c["category"] for c in category_insights if c["position"] == "value"]
            }
        },
        "top_categories": {
            "by_price": [
                {"category": cat, "name": data["name"], "avg_price": data["avg_price"]}
                for cat, data in sorted_by_price[:5]
            ],
            "by_mrr": [
                {"category": cat, "name": data["name"], "median_mrr": data["median_mrr"]}
                for cat, data in sorted_by_mrr[:5]
            ]
        },
        "category_details": category_insights,
        "market_trends": trends
    })


@app.route("/api/market/compare", methods=["POST"])
@require_api_key
def compare_categories():
    """Compare pricing across multiple categories."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    categories = data.get("categories", [])

    if not categories:
        return jsonify({"error": "categories array is required"}), 400

    if len(categories) < 2:
        return jsonify({"error": "At least 2 categories required for comparison"}), 400

    if len(categories) > 5:
        return jsonify({"error": "Maximum 5 categories per comparison"}), 400

    from src.benchmarks import INDUSTRY_BENCHMARKS

    comparison = []
    for cat in categories:
        if cat in INDUSTRY_BENCHMARKS:
            data = INDUSTRY_BENCHMARKS[cat]
            comparison.append({
                "category": cat,
                "name": data["name"],
                "avg_price": data["avg_price"],
                "price_range_low": data["price_range_low"],
                "price_range_high": data["price_range_high"],
                "median_mrr": data["median_mrr"],
                "typical_discount": data["typical_discount"]
            })
        else:
            comparison.append({
                "category": cat,
                "error": "Category not found"
            })

    # Calculate price differences
    valid_cats = [c for c in comparison if "avg_price" in c]
    if len(valid_cats) >= 2:
        prices = [c["avg_price"] for c in valid_cats]
        max_price = max(prices)
        min_price = min(prices)
        price_spread = max_price - min_price
        price_spread_pct = (price_spread / min_price) * 100 if min_price > 0 else 0

        spread_analysis = {
            "highest_price": max_price,
            "lowest_price": min_price,
            "price_spread": round(price_spread, 2),
            "price_spread_percentage": round(price_spread_pct, 1),
            "insight": "High price variation - significant positioning differences" if price_spread_pct > 50 else "Moderate price variation"
        }
    else:
        spread_analysis = None

    return jsonify({
        "comparison": comparison,
        "spread_analysis": spread_analysis
    })


@app.route("/api/v1/price-elasticity", methods=["POST"])
@require_api_key
def analyze_price_elasticity():
    """Analyze price elasticity of demand for a SaaS product.

    Price elasticity measures how demand responds to price changes.
    - Elastic (|E| > 1): demand is sensitive to price
    - Inelastic (|E| < 1): demand is insensitive to price

    Request Body (JSON):
        current_price (float): Current monthly price (required)
        customer_segment (str): Target segment - smb, startup, or enterprise (default: smb)
        market_category (str): Industry category (default: default)

    Returns:
        Elasticity analysis with optimal pricing recommendations
    """
    from src.benchmarks import calculate_price_elasticity

    data = request.get_json()

    if not data:
        logger.warning("Price elasticity analysis failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    # Validate current_price
    try:
        current_price = float(data.get("current_price"))
        if current_price <= 0:
            logger.warning(f"Invalid current_price: {current_price} (must be positive)")
            return jsonify({"error": "current_price must be a positive number"}), 400
    except (TypeError, ValueError) as e:
        logger.warning(f"Price elasticity analysis failed: Invalid price value: {data.get('current_price')}")
        return jsonify({"error": f"Invalid current_price: {str(e)}"}), 400

    # Validate customer_segment
    customer_segment = data.get("customer_segment", "smb")
    valid_segments = ["smb", "startup", "enterprise"]
    if customer_segment not in valid_segments:
        logger.warning(f"Invalid customer_segment: {customer_segment}")
        return jsonify({"error": f"customer_segment must be one of: {valid_segments}"}), 400

    market_category = data.get("market_category", "default")

    logger.info(f"Price elasticity analysis: price=${current_price}, segment={customer_segment}")

    # Calculate elasticity
    elasticity_analysis = calculate_price_elasticity(
        current_price=current_price,
        customer_segment=customer_segment,
        market_category=market_category,
    )

    return jsonify({
        "success": True,
        "analysis": elasticity_analysis,
        "recommendation": {
            "optimal_price": elasticity_analysis["optimal_price"],
            "price_change": f"{'+' if elasticity_analysis['optimal_price_change_pct'] > 0 else ''}{elasticity_analysis['optimal_price_change_pct']}%",
            "expected_revenue_impact": f"{'+' if elasticity_analysis['potential_revenue_gain_pct'] > 0 else ''}{elasticity_analysis['potential_revenue_gain_pct']}%",
            "insight": elasticity_analysis["description"],
        }
    })


@app.route("/api/v1/charm-pricing", methods=["POST"])
@require_api_key
def analyze_charm_pricing():
    """Analyze and optimize pricing using psychological pricing strategies.

    Charm pricing uses psychological tactics to increase conversions:
    - Classic: ending in 9 (e.g., $99)
    - Prestige: ending in 7 (e.g., $97)
    - Strategic: ending in 5 (e.g., $95)
    - Luxury: ending in 8 or 9 (e.g., $98, $99)
    - Round: rounded to nearest dollar

    Research shows prices ending in .99 or .97 can increase conversion
    rates by 15-25% compared to round numbers.

    Request Body (JSON):
        base_price (float): The recommended price to optimize (required)
        strategy (str): Pricing strategy - classic, prestige, strategic, luxury, round (default: classic)

    Returns:
        Charm pricing analysis with recommended prices and conversion uplift estimates
    """
    data = request.get_json()

    if not data:
        logger.warning("Charm pricing analysis failed: No data provided")
        return jsonify({"error": "No data provided"}), 400

    # Validate base_price
    try:
        base_price = float(data.get("base_price"))
        if base_price <= 0:
            logger.warning(f"Invalid base_price: {base_price} (must be positive)")
            return jsonify({"error": "base_price must be a positive number"}), 400
    except (TypeError, ValueError) as e:
        logger.warning(f"Charm pricing analysis failed: Invalid price value: {data.get('base_price')}")
        return jsonify({"error": f"Invalid base_price: {str(e)}"}), 400

    # Validate strategy
    strategy = data.get("strategy", "classic")
    valid_strategies = ["classic", "prestige", "strategic", "luxury", "round"]
    if strategy not in valid_strategies:
        logger.warning(f"Invalid strategy: {strategy}")
        return jsonify({"error": f"strategy must be one of: {valid_strategies}"}), 400

    logger.info(f"Charm pricing analysis: base_price=${base_price}, strategy={strategy}")

    # Calculate charm pricing
    charm_analysis = calculate_charm_pricing(
        base_price=base_price,
        strategy=strategy,
    )

    return jsonify({
        "success": True,
        "analysis": charm_analysis,
        "recommendation": {
            "optimal_charm_price": charm_analysis["best_charm_price"],
            "adjustment_type": charm_analysis["best_adjustment"],
            "expected_conversion_uplift": charm_analysis["conversion_uplift_estimate"],
            "psychological_insight": charm_analysis["psychological_benefit"],
        }
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
