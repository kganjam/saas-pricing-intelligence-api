"""
SaaS Pricing Intelligence API - Flask Backend
Aggregates and analyzes SaaS pricing data.
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app)

# In-memory data store (would be database in production)
pricing_data = {}
products_db = {}


def init_sample_data():
    """Initialize with sample SaaS pricing data."""
    sample_products = [
        {"id": "slack", "name": "Slack", "category": "Collaboration", "url": "slack.com"},
        {"id": "notion", "name": "Notion", "category": "Productivity", "url": "notion.so"},
        {"id": "airtable", "name": "Airtable", "category": "Database", "url": "airtable.com"},
        {"id": "hubspot", "name": "HubSpot", "category": "CRM", "url": "hubspot.com"},
        {"id": "salesforce", "name": "Salesforce", "category": "CRM", "url": "salesforce.com"},
        {"id": "zoom", "name": "Zoom", "category": "Video", "url": "zoom.us"},
        {"id": "dropbox", "name": "Dropbox", "category": "Storage", "url": "dropbox.com"},
        {"id": "shopify", "name": "Shopify", "category": "E-commerce", "url": "shopify.com"},
        {"id": "mailchimp", "name": "Mailchimp", "category": "Email", "url": "mailchimp.com"},
        {"id": "zendesk", "name": "Zendesk", "category": "Support", "url": "zendesk.com"},
    ]

    # Sample pricing tiers for each product
    for product in sample_products:
        products_db[product["id"]] = product
        pricing_data[product["id"]] = [
            {
                "tier": "Free",
                "price": 0,
                "users": "1-10",
                "features": ["Basic features"]
            },
            {
                "tier": "Starter",
                "price": 8,
                "users": "1-50",
                "features": ["More features", "Priority support"]
            },
            {
                "tier": "Pro",
                "price": 25,
                "users": "Unlimited",
                "features": ["All features", "API access", "Analytics"]
            },
            {
                "tier": "Enterprise",
                "price": 75,
                "users": "Unlimited",
                "features": ["Custom", "SSO", "SLA", "Dedicated support"]
            }
        ]


# Initialize sample data on startup
init_sample_data()


@app.route('/')
def index():
    """Serve the landing page."""
    return send_from_directory('.', 'landing.html')


@app.route('/api/products', methods=['GET'])
def list_products():
    """List all tracked SaaS products."""
    category = request.args.get('category')
    search = request.args.get('search', '').lower()

    results = []
    for pid, product in products_db.items():
        if category and product.get('category') != category:
            continue
        if search and search not in product['name'].lower():
            continue
        results.append({
            'id': pid,
            'name': product['name'],
            'category': product['category'],
            'url': product['url']
        })

    return jsonify({
        'success': True,
        'count': len(results),
        'products': results
    })


@app.route('/api/pricing/<product_id>', methods=['GET'])
def get_pricing(product_id):
    """Get pricing tiers for a specific product."""
    if product_id not in pricing_data:
        return jsonify({
            'success': False,
            'error': 'Product not found'
        }), 404

    product = products_db[product_id]
    tiers = pricing_data[product_id]

    return jsonify({
        'success': True,
        'product': {
            'id': product_id,
            'name': product['name'],
            'category': product['category'],
            'url': product['url']
        },
        'pricing': tiers,
        'last_updated': datetime.utcnow().isoformat()
    })


@app.route('/api/compare', methods=['POST'])
def compare_products():
    """Compare pricing across multiple products."""
    data = request.json
    product_ids = data.get('products', [])

    if not product_ids:
        return jsonify({
            'success': False,
            'error': 'No products specified'
        }), 400

    comparison = []
    for pid in product_ids:
        if pid not in products_db:
            continue
        product = products_db[pid]
        tiers = pricing_data[pid]

        # Find lowest and highest prices
        prices = [t['price'] for t in tiers]
        comparison.append({
            'id': pid,
            'name': product['name'],
            'category': product['category'],
            'min_price': min(prices),
            'max_price': max(prices),
            'tiers': tiers
        })

    return jsonify({
        'success': True,
        'comparison': comparison
    })


@app.route('/api/trends', methods=['GET'])
def get_trends():
    """Get pricing trends across categories."""
    category = request.args.get('category')

    # Calculate average prices by category
    category_prices = {}
    for pid, product in products_db.items():
        cat = product.get('category')
        if category and cat != category:
            continue

        tiers = pricing_data[pid]
        avg_price = sum(t['price'] for t in tiers) / len(tiers)

        if cat not in category_prices:
            category_prices[cat] = []
        category_prices[cat].append(avg_price)

    trends = []
    for cat, prices in category_prices.items():
        trends.append({
            'category': cat,
            'avg_price': round(sum(prices) / len(prices), 2),
            'product_count': len(prices),
            'min_avg': min(prices),
            'max_avg': max(prices)
        })

    return jsonify({
        'success': True,
        'trends': trends,
        'generated_at': datetime.utcnow().isoformat()
    })


@app.route('/api/search', methods=['GET'])
def search_products():
    """Search products by features or price range."""
    query = request.args.get('q', '').lower()
    max_price = request.args.get('max_price', type=float)

    results = []
    for pid, product in products_db.items():
        tiers = pricing_data[pid]
        prices = [t['price'] for t in tiers]

        # Filter by max price
        if max_price is not None and max(prices) > max_price:
            continue

        # Search in name or features
        match = False
        if query in product['name'].lower():
            match = True
        if query in product.get('category', '').lower():
            match = True
        for tier in tiers:
            if any(query in f.lower() for f in tier.get('features', [])):
                match = True

        if match or not query:
            results.append({
                'id': pid,
                'name': product['name'],
                'category': product['category'],
                'starting_price': min(prices),
                'pricing_tiers': len(tiers)
            })

    return jsonify({
        'success': True,
        'query': query,
        'results': results,
        'count': len(results)
    })


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint for load balancers."""
    return jsonify({'status': 'healthy', 'service': 'SaaS Pricing Intelligence API'})

@app.route('/api/status', methods=['GET'])
def status():
    """Return service status."""
    return jsonify({
        'service': 'SaaS Pricing Intelligence API',
        'version': '1.0.0',
        'status': 'operational',
        'products_indexed': len(products_db),
        'endpoints': [
            '/api/products',
            '/api/pricing/<id>',
            '/api/compare',
            '/api/trends',
            '/api/search'
        ]
    })


@app.route('/api/pricing', methods=['GET'])
def pricing():
    """Return pricing tiers for API access."""
    return jsonify({
        'tiers': [
            {
                'name': 'Developer',
                'price': 0,
                'requests': 100,
                'products': 10,
                'features': ['Basic pricing data', '5 searches/day']
            },
            {
                'name': 'Startup',
                'price': 49,
                'requests': 5000,
                'products': 100,
                'features': ['Full pricing data', '100 searches/day', 'CSV export']
            },
            {
                'name': 'Business',
                'price': 199,
                'requests': 50000,
                'products': 1000,
                'features': ['Historical data', 'Unlimited searches', 'API access', 'Email reports']
            },
            {
                'name': 'Enterprise',
                'price': 499,
                'requests': -1,
                'products': -1,
                'features': ['Custom data feeds', 'White-label', 'Dedicated support', 'SLA']
            }
        ]
    })


@app.route('/api/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events for payment tracking."""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    # In production, verify the webhook signature
    # For now, just log the event type
    event_data = request.get_json() or {}

    event_type = event_data.get('type', 'unknown')
    print(f"Stripe webhook received: {event_type}")

    # Handle successful payments
    if event_type == 'checkout.session.completed':
        session = event_data.get('data', {}).get('object', {})
        customer_email = session.get('customer_email')
        amount_total = session.get('amount_total', 0) / 100  # Convert cents to dollars

        print(f"Payment received: ${amount_total} from {customer_email}")

        return jsonify({'success': True, 'event': 'payment_received'})

    return jsonify({'success': True, 'event': 'processed'})


@app.route('/api/signups', methods=['GET', 'POST'])
def signups():
    """Track or retrieve signup data."""
    if request.method == 'POST':
        data = request.get_json() or {}
        email = data.get('email')
        plan = data.get('plan', 'developer')

        # In production, this would store to a database
        print(f"New signup: {email} on plan {plan}")

        return jsonify({
            'success': True,
            'message': 'Signup recorded',
            'plan': plan
        })
    else:
        # Return signup count (in production, fetch from database)
        return jsonify({
            'success': True,
            'total_signups': 0,
            'note': 'Signups tracked via Stripe webhooks in production'
        })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
