# Deployment Guide: SaaS Pricing Intelligence API

## Quick Deploy to Render

### Option 1: Render Dashboard (Recommended)

1. **Create a Render account**
   - Go to [render.com](https://render.com) and sign up with GitHub

2. **Create a new Web Service**
   - Click "New" → "Web Service"
   - Connect your GitHub repository containing this prototype
   - Select the `idea-saas-pricing-intelligence` directory

3. **Configure the service**
   - Name: `saas-pricing-api`
   - Environment: `Python`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python server.py`
   - Plan: Free

4. **Deploy**
   - Click "Create Web Service"
   - Wait for build to complete (~2-3 minutes)

### Option 2: Render CLI

```bash
# Install Render CLI
brew install render-cli # or npm install -g @render/cli

# Login
render auth login

# Deploy from prototype directory
cd data/prototypes/idea-saas-pricing-intelligence
render deploy --service-name saas-pricing-api --plan free
```

## Configure Stripe Payments

### Create Products in Stripe

1. Go to [dashboard.stripe.com](https://dashboard.stripe.com)
2. Create products for each tier:
   - Developer (Free): $0/month
   - Startup: $49/month
   - Business: $199/month
   - Enterprise: $499/month

3. Create Payment Links for each product
4. Copy the payment link URLs

### Update Landing Page

Edit `landing.html` and replace the test links:

```html
<!-- Find and replace these URLs -->
<a href="https://buy.stripe.com/YOUR_REAL_LINK" class="cta">
```

### Set Webhook (Optional)

For payment verification, set up a Stripe webhook:

1. Go to Stripe Dashboard → Developers → Webhooks
2. Add endpoint: `https://your-render-url.onrender.com/api/webhook/stripe`
3. Select events: `checkout.session.completed`, `customer.subscription.created`

## Verify Deployment

1. **API Health**: Visit `https://your-render-url.onrender.com/api/status`
2. **Landing Page**: Visit `https://your-render-url.onrender.com/`
3. **Test Checkout**: Click a pricing button to verify Stripe checkout opens

## Troubleshooting

- **Slow first request**: Render's free tier sleeps after 15 min of inactivity. First request may take 30+ seconds.
- **502 errors**: Check that the PORT environment variable is set to 5000
- **Import errors**: Ensure all dependencies in requirements.txt are installed
