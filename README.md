# SaaS Pricing Intelligence API

AI-powered pricing intelligence for SaaS products.

## Overview

SaaS Pricing Intelligence API analyzes market data, competitor pricing, and customer segments to recommend optimal pricing strategies for SaaS companies.

## Features

- Competitor pricing analysis
- Customer segment-based pricing
- Price elasticity modeling
- MRR optimization recommendations
- Usage-based pricing intelligence

## Pricing Tiers

| Tier | Monthly Price | Features |
|------|--------------|----------|
| Starter | $49 | 100 API calls/mo, basic analytics |
| Growth | $199 | 1,000 API calls/mo, advanced analytics, competitor tracking |
| Enterprise | $999 | Unlimited API calls, custom models, dedicated support |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the prototype
python -m src.main

# Run tests
pytest tests/
```

## API Usage

```python
from src.app import PricingIntelligenceEngine, PricingRequest

engine = PricingIntelligenceEngine()
request = PricingRequest(
    product_name="My SaaS Product",
    current_price=99,
    competitors=["competitor_a", "competitor_b"],
    customer_segment="smb",
    features=["feature1", "feature2"]
)

recommendation = engine.analyze(request)
print(recommendation)
```

## Deployment

### Quick Deploy to Render (Free)

1. Push this code to a GitHub repository
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Create a new "Web Service" and connect to your GitHub repo
4. Render will automatically detect the `render.yaml` configuration
5. Add environment variables:
   - `FLASK_ENV=production`
   - `PORT=5000`
6. Your API will be live at `https://your-service-name.onrender.com`

### Manual Deployment

```bash
# Using Docker
docker build -t saas-pricing-api .
docker run -p 5000:5000 saas-pricing-api

# Using docker-compose
docker-compose up -d
```

### Stripe Payment Integration

1. Create a [Stripe account](https://stripe.com)
2. Create Payment Links for each pricing tier:
   - Starter ($0): Free signup
   - Startup ($49/mo): Monthly subscription
   - Business ($199/mo): Monthly subscription
   - Enterprise ($499/mo): Contact sales
3. Replace the test URLs in `landing.html`:
   - `https://buy.stripe.com/test_starter`
   - `https://buy.stripe.com/test_startup`
   - `https://buy.stripe.com/test_business`
   with your real Stripe Payment Links
4. Optionally configure Stripe Webhooks to point to `/api/webhook/stripe`

## Deployment Checklist

Run this script after deployment to verify everything works:

```bash
./verify_deployment.sh https://your-service.onrender.com
```

### Steps to Deploy

1. **Push to GitHub**: Ensure this code is in a GitHub repository
2. **Connect to Render**:
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Create a new Web Service
   - Connect to your GitHub repository
   - Render will auto-detect `render.yaml`
3. **Configure Environment**:
   - `FLASK_ENV=production`
   - `PORT=5000`
4. **Deploy**: Click Deploy
5. **Verify**: Run `./verify_deployment.sh https://your-url.onrender.com`
6. **Wire Stripe**: Replace test links in `landing.html` with real Payment Links

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| PORT | HTTP port | 5000 |
| FLASK_ENV | Environment | development |
| STRIPE_WEBHOOK_SECRET | Stripe webhook signing secret | - |
