# Stripe Payment Setup Guide

This guide explains how to configure real Stripe payment links for SaaS Pricing Intelligence API.

## Quick Start (Payment Links)

The simplest way to accept payments:

1. **Create a Stripe account** at [stripe.com](https://stripe.com)
2. **Create Products** in Stripe Dashboard:
   - Developer (Free): $0/month
   - Startup: $49/month
   - Business: $199/month
   - Enterprise: $499/month (use mailto)

3. **Create Payment Links** for each paid product:
   - Copy the payment link URL from Stripe
   - Update `landing.html` with real URLs

4. **Update landing.html**:
   ```html
   <!-- Find these lines and replace with real Stripe links -->
   <a href="https://buy.stripe.com/your_real_link" class="cta">Get Started</a>
   ```

## Configuration in landing.html

The payment links are in the pricing section (around line 197-234):

```html
<!-- Developer (Free) -->
<a href="https://buy.stripe.com/your_link" class="cta secondary" onclick="trackSignup('developer')">Start Free</a>

<!-- Startup ($49/mo) -->
<a href="https://buy.stripe.com/your_link" class="cta" onclick="trackSignup('startup')">Get Started</a>

<!-- Business ($199/mo) -->
<a href="https://buy.stripe.com/your_link" class="cta secondary" onclick="trackSignup('business')">Get Started</a>

<!-- Enterprise ($499/mo) -->
<a href="mailto:sales@saaspricingapi.com?subject=Enterprise%20Pricing" class="cta secondary">Contact Sales</a>
```

## Testing

Use Stripe's test mode:
- Test card: 4242 4242 4242 4242
- Any future expiry date
- Any CVC

Test payment links start with `https://buy.stripe.com/test_`

## Webhook Setup (Optional)

For production payment tracking, set up Stripe webhooks:

1. Go to Stripe Dashboard → Webhooks
2. Add endpoint: `https://your-domain.com/api/webhook/stripe`
3. Select events: `checkout.session.completed`
4. Add webhook secret to server environment

## Deployment

Deploy to Render.com:
1. Push code to GitHub
2. Connect repository in Render dashboard
3. The `render.yaml` will auto-configure the service
4. Add environment variables in Render:
   - `STRIPE_WEBHOOK_SECRET` (from Stripe)
   - `STRIPE_SECRET_KEY` (for server-side operations)

## Tracking Payments

The landing page tracks signups in localStorage:
```javascript
// View signup data
JSON.parse(localStorage.getItem('pricing_api_signups'))
```

For production, use Stripe Dashboard or set up webhooks.
