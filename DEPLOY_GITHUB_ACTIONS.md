# Deployment Setup

This directory contains multiple deployment configurations for the SaaS Pricing Intelligence API.

## Quick Deploy Options

### Option 1: GitHub Actions (Recommended)

1. Fork this repository to your GitHub account
2. Go to your repository settings → Secrets and variables → Actions
3. Add the following secrets:
   - `RENDER_API_KEY`: Your Render.com API key
   - `RAILWAY_TOKEN`: Your Railway.app token (optional)
   - `FLY_API_TOKEN`: Your Fly.io API token (optional)
4. Go to Actions → Deploy to Render → Run workflow

### Option 2: Render.com (Manual)

1. Go to [render.com](https://render.com) and sign in
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Render will auto-detect `render.yaml`
5. Click "Create Web Service"

### Option 3: Fly.io CLI

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Authenticate
fly auth login

# Deploy
fly launch --name saas-pricing-api --yes
fly deploy
```

### Option 4: Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway deploy
```

## API Endpoints

Once deployed, the API provides these endpoints:

- `GET /` - Landing page
- `GET /api/products` - List all products
- `GET /api/pricing/<product>` - Get pricing for a product
- `GET /api/trends` - Get pricing trends
- `POST /api/recommend` - Get pricing recommendations

## Environment Variables

- `FLASK_ENV`: production (default)
- `PORT`: 5000 (Render), 8080 (Docker)

## Testing

Run tests locally:
```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```
