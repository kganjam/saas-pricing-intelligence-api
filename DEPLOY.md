# Deployment Guide - SaaS Pricing Intelligence API

## Quick Deploy to Render.com

### Option 1: Automatic Deploy (Recommended)

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Deploy SaaS Pricing API"
   git push origin main
   ```

2. **Connect to Render**
   - Go to [render.com](https://render.com) and sign up
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Render will auto-detect the `render.yaml` configuration

3. **Environment Variables** (optional)
   - `STRIPE_WEBHOOK_SECRET`: Your Stripe webhook signing secret
   - `FLASK_ENV`: production

4. **Deploy**
   - Click "Create Web Service"
   - Wait for build to complete (~2-3 minutes)
   - Your API will be live at `https://saas-pricing-api.onrender.com`

### Option 2: Manual Deploy

```bash
# Clone and deploy manually
git clone https://github.com/your-repo/idea-saas-pricing-intelligence.git
cd idea-saas-pricing-intelligence
pip install -r requirements.txt
python server.py
```

## Verify Deployment

Test the API endpoints:

```bash
# Check API status
curl https://your-domain.onrender.com/api/status

# List products
curl https://your-domain.onrender.com/api/products

# Get pricing for a product
curl https://your-domain.onrender.com/api/pricing/slack
```

## Landing Page

The landing page is served at the root URL:
- `https://your-domain.onrender.com/` → landing page with pricing
- `https://your-domain.onrender.com/api/products` → API endpoint

## Configure Payments

1. Create Stripe account at [stripe.com](https://stripe.com)
2. Create products with pricing tiers
3. Generate payment links
4. Update `landing.html` with real payment links
5. See `STRIPE_SETUP.md` for detailed instructions

## Free Tier Limits

Render's free tier:
- Sleeps after 15 minutes of inactivity
- 750 hours per month
- Build times apply to this limit

For production, upgrade to a paid plan ($7/month).
