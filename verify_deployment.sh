#!/bin/bash
# Deployment verification script for SaaS Pricing Intelligence API
# Run this after deploying to verify end-to-end functionality

BASE_URL="${1:-http://localhost:5000}"

echo "=== SaaS Pricing Intelligence API Deployment Verification ==="
echo ""
echo "Testing base URL: $BASE_URL"
echo ""

# Test 1: Service status
echo "1. Testing /api/status..."
STATUS=$(curl -s "$BASE_URL/api/status")
if echo "$STATUS" | grep "operational" > /dev/null 2>&1; then
    echo "   ✓ Service is operational"
else
    echo "   ✗ Service status check failed"
    exit 1
fi

# Test 2: Products endpoint
echo "2. Testing /api/products..."
PRODUCTS=$(curl -s "$BASE_URL/api/products")
if echo "$PRODUCTS" | grep "success" > /dev/null 2>&1; then
    echo "   ✓ Products endpoint working"
else
    echo "   ✗ Products endpoint failed"
    exit 1
fi

# Test 3: Pricing endpoint
echo "3. Testing /api/pricing/slack..."
PRICING=$(curl -s "$BASE_URL/api/pricing/slack")
if echo "$PRICING" | grep "success" > /dev/null 2>&1; then
    echo "   ✓ Pricing endpoint working"
else
    echo "   ✗ Pricing endpoint failed"
    exit 1
fi

# Test 4: Search endpoint
echo "4. Testing /api/search..."
SEARCH=$(curl -s "$BASE_URL/api/search?q=collaboration")
if echo "$SEARCH" | grep "success" > /dev/null 2>&1; then
    echo "   ✓ Search endpoint working"
else
    echo "   ✗ Search endpoint failed"
    exit 1
fi

# Test 5: Trends endpoint
echo "5. Testing /api/trends..."
TRENDS=$(curl -s "$BASE_URL/api/trends")
if echo "$TRENDS" | grep "success" > /dev/null 2>&1; then
    echo "   ✓ Trends endpoint working"
else
    echo "   ✗ Trends endpoint failed"
    exit 1
fi

# Test 6: Landing page
echo "6. Testing landing page..."
LANDING=$(curl -s "$BASE_URL/")
if echo "$LANDING" | grep "SaaS Pricing Intelligence" > /dev/null 2>&1; then
    echo "   ✓ Landing page serving correctly"
else
    echo "   ✗ Landing page check failed"
    exit 1
fi

# Test 7: API pricing tiers
echo "7. Testing /api/pricing (API tiers)..."
API_PRICING=$(curl -s "$BASE_URL/api/pricing")
if echo "$API_PRICING" | grep "tiers" > /dev/null 2>&1; then
    echo "   ✓ API pricing tiers endpoint working"
else
    echo "   ✗ API pricing tiers failed"
    exit 1
fi

echo ""
echo "=== All Tests Passed ==="
echo ""
echo "Deployment verification complete!"
echo ""
echo "Next steps for Stripe integration:"
echo "1. Create a Stripe account at https://stripe.com"
echo "2. Create Payment Links for each pricing tier"
echo "3. Replace test URLs in landing.html with real Stripe Payment Links"
echo "4. Configure Stripe Webhooks to point to /api/webhook/stripe"
