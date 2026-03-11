"""API endpoint tests for SaaS Pricing Intelligence API."""

import sys
from pathlib import Path
import json
import pytest

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import app


@pytest.fixture
def client():
    """Create test client for Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get('/api/health')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['status'] == 'healthy'


def test_status_endpoint(client):
    """Test status endpoint."""
    response = client.get('/api/status')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert 'products_tracked' in data
    assert data['products_tracked'] > 0


def test_list_products(client):
    """Test listing all products."""
    response = client.get('/api/products')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert len(data['products']) > 0


def test_list_products_with_category(client):
    """Test filtering products by category."""
    response = client.get('/api/products?category=CRM')
    data = json.loads(response.data)
    assert response.status_code == 200
    for product in data['products']:
        assert product['category'] == 'CRM'


def test_list_products_with_search(client):
    """Test searching products by name."""
    response = client.get('/api/products?search=slack')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert len(data['products']) > 0
    assert 'slack' in data['products'][0]['name'].lower()


def test_get_pricing_for_product(client):
    """Test getting pricing for a specific product."""
    response = client.get('/api/pricing/slack')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert data['product']['name'] == 'Slack'
    assert len(data['pricing']) > 0


def test_get_pricing_for_nonexistent_product(client):
    """Test getting pricing for non-existent product."""
    response = client.get('/api/pricing/nonexistent')
    data = json.loads(response.data)
    assert response.status_code == 404
    assert data['success'] is False


def test_compare_products(client):
    """Test comparing multiple products."""
    response = client.post('/api/compare', json={
        'products': ['slack', 'notion', 'airtable']
    })
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert len(data['comparison']) == 3


def test_compare_empty_products(client):
    """Test compare with no products."""
    response = client.post('/api/compare', json={'products': []})
    data = json.loads(response.data)
    assert response.status_code == 400
    assert data['success'] is False


def test_get_trends(client):
    """Test getting pricing trends."""
    response = client.get('/api/trends')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert len(data['trends']) > 0


def test_get_trends_with_category(client):
    """Test trends with category filter."""
    response = client.get('/api/trends?category=CRM')
    data = json.loads(response.data)
    assert response.status_code == 200
    for trend in data['trends']:
        assert trend['category'] == 'CRM'


def test_search_products_by_query(client):
    """Test searching products."""
    response = client.get('/api/search?q=api')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert len(data['results']) > 0


def test_search_with_max_price(client):
    """Test searching with price filter."""
    response = client.get('/api/search?max_price=20')
    data = json.loads(response.data)
    assert response.status_code == 200
    for result in data['results']:
        assert result['starting_price'] <= 20


def test_pricing_tiers(client):
    """Test API pricing tiers endpoint."""
    response = client.get('/api/pricing')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert 'tiers' in data
    assert len(data['tiers']) == 4


@pytest.mark.skip(reason="Endpoint not implemented")
def test_benchmark_pricing(client):
    """Test benchmark pricing endpoint."""
    response = client.post('/api/benchmark', json={
        'product_name': 'My SaaS',
        'current_price': 50.0,
        'category': 'Project Management'
    })
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert 'market_average' in data


@pytest.mark.skip(reason="Endpoint not implemented")
def test_benchmark_pricing_missing_fields(client):
    """Test benchmark with missing required fields."""
    response = client.post('/api/benchmark', json={
        'product_name': 'Test'
        # Missing current_price
    })
    data = json.loads(response.data)
    assert response.status_code == 400


@pytest.mark.skip(reason="Endpoint not implemented")
def test_revenue_estimate(client):
    """Test revenue estimation endpoint."""
    response = client.get('/api/revenue/estimate?tier=growth&customers=50')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert data['monthly_revenue'] == 199 * 50


@pytest.mark.skip(reason="Endpoint not implemented")
def test_recommend_pricing(client):
    """Test AI pricing recommendation endpoint."""
    response = client.post('/api/recommend', json={
        'product_name': 'New SaaS',
        'current_price': 99.0,
        'customer_segment': 'smb',
        'features': ['api_access', 'analytics'],
        'competitors': ['comp_a', 'comp_b']
    })
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True
    assert 'recommended_price' in data['recommendation']


@pytest.mark.skip(reason="Endpoint not implemented")
def test_recommend_pricing_missing_fields(client):
    """Test recommend with missing required fields."""
    response = client.post('/api/recommend', json={
        'product_name': 'Test'
        # Missing current_price and customer_segment
    })
    data = json.loads(response.data)
    assert response.status_code == 400


def test_signup_endpoint_post(client):
    """Test signup endpoint."""
    response = client.post('/api/signups', json={
        'email': 'test@example.com',
        'plan': 'growth'
    })
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True


def test_signup_endpoint_get(client):
    """Test getting signup count."""
    response = client.get('/api/signups')
    data = json.loads(response.data)
    assert response.status_code == 200
    assert 'total_signups' in data


def test_stripe_webhook(client):
    """Test Stripe webhook endpoint."""
    response = client.post('/api/webhook/stripe', json={
        'type': 'checkout.session.completed',
        'data': {
            'object': {
                'customer_email': 'test@example.com',
                'amount_total': 4900
            }
        }
    })
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data['success'] is True


def test_index_route(client):
    """Test index route serves landing page."""
    response = client.get('/')
    assert response.status_code == 200
