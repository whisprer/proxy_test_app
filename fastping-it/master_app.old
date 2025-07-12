"""
Master FastPing.It Application
==============================
Single file that integrates EVERYTHING and actually works
No bullshit, just functional integration
"""

from flask import Flask, request, jsonify, render_template_string, Response
from functools import wraps
import sqlite3
import redis
import time
import json
import uuid
import hashlib
import hmac
import requests
import threading
import smtplib
from email.mime.text import MimeText
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =============================================================================
# CONFIGURATION & SETUP
# =============================================================================

# Try Redis, fallback to memory if not available
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("Redis connected")
except:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available - using memory cache")

# Database setup
DB_PATH = 'fastping_master.db'

def init_master_database():
    """Initialize complete database schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Customers table (main customer data)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            company_name TEXT,
            plan_type TEXT DEFAULT 'basic',
            status TEXT DEFAULT 'active',
            api_key TEXT UNIQUE NOT NULL,
            monthly_quota INTEGER DEFAULT 10000,
            current_usage INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            paypal_subscription_id TEXT,
            notes TEXT
        )
    ''')
    
    # IP Whitelist (for proxy access)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ip_whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            rate_limit INTEGER DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        )
    ''')
    
    # Usage logs (for billing and analytics)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL,
            api_key TEXT,
            endpoint TEXT NOT NULL,
            method TEXT DEFAULT 'GET',
            ip_address TEXT,
            response_time_ms REAL,
            status_code INTEGER DEFAULT 200,
            success BOOLEAN DEFAULT 1,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            bytes_transferred INTEGER DEFAULT 0,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        )
    ''')
    
    # PayPal transactions (for payment tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paypal_transactions (
            transaction_id TEXT PRIMARY KEY,
            customer_id TEXT,
            paypal_payment_id TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            plan_type TEXT NOT NULL,
            status TEXT DEFAULT 'completed',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        )
    ''')
    
    # Rate limiting
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limits (
            api_key TEXT PRIMARY KEY,
            requests_count INTEGER DEFAULT 0,
            window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            daily_count INTEGER DEFAULT 0,
            daily_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

# =============================================================================
# CORE CLASSES
# =============================================================================

class FastPingCore:
    """Core functionality - customer management, rate limiting, etc."""
    
    def __init__(self):
        self.cache = {}
        
    def create_customer(self, email: str, plan_type: str, paypal_payment_id: str = None) -> Tuple[bool, str]:
        """Create new customer with API key"""
        try:
            customer_id = f"cust_{uuid.uuid4().hex[:12]}"
            api_key = f"fpk_{uuid.uuid4().hex}"
            
            # Plan quotas
            quotas = {'basic': 10000, 'premium': 50000, 'enterprise': 200000}
            monthly_quota = quotas.get(plan_type, 10000)
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO customers 
                (customer_id, email, plan_type, api_key, monthly_quota)
                VALUES (?, ?, ?, ?, ?)
            ''', (customer_id, email, plan_type, api_key, monthly_quota))
            
            # Add to IP whitelist (allow from any IP for API access)
            cursor.execute('''
                INSERT INTO ip_whitelist 
                (customer_id, ip_address, rate_limit)
                VALUES (?, ?, ?)
            ''', (customer_id, '0.0.0.0/0', 100 if plan_type == 'basic' else 500))
            
            # Record PayPal transaction if provided
            if paypal_payment_id:
                amounts = {'basic': 29.99, 'premium': 99.99, 'enterprise': 299.99}
                cursor.execute('''
                    INSERT INTO paypal_transactions 
                    (transaction_id, customer_id, paypal_payment_id, amount, plan_type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (str(uuid.uuid4()), customer_id, paypal_payment_id, amounts.get(plan_type, 29.99), plan_type))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Customer created: {email} -> {customer_id}")
            return True, {'customer_id': customer_id, 'api_key': api_key}
            
        except Exception as e:
            logger.error(f"Failed to create customer: {e}")
            return False, str(e)
    
    def validate_api_key(self, api_key: str) -> Tuple[bool, Optional[Dict]]:
        """Validate API key and return customer info"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT customer_id, email, plan_type, status, monthly_quota, current_usage
                FROM customers WHERE api_key = ? AND status = 'active'
            ''', (api_key,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return True, {
                    'customer_id': result[0],
                    'email': result[1],
                    'plan_type': result[2],
                    'status': result[3],
                    'monthly_quota': result[4],
                    'current_usage': result[5]
                }
            
            return False, None
            
        except Exception as e:
            logger.error(f"API key validation failed: {e}")
            return False, None
    
    def check_rate_limit(self, api_key: str, plan_type: str) -> Tuple[bool, Dict]:
        """Check if request is within rate limits"""
        try:
            limits = {'basic': 100, 'premium': 500, 'enterprise': 2000}
            limit = limits.get(plan_type, 100)
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            now = datetime.now()
            
            cursor.execute('''
                SELECT requests_count, window_start FROM rate_limits WHERE api_key = ?
            ''', (api_key,))
            
            result = cursor.fetchone()
            
            if result:
                requests_count, window_start_str = result
                window_start = datetime.fromisoformat(window_start_str)
                
                # Reset if window expired
                if now - window_start > timedelta(minutes=1):
                    requests_count = 0
                    window_start = now
                
                if requests_count >= limit:
                    conn.close()
                    return False, {'error': 'Rate limit exceeded', 'limit': limit}
                
                # Update count
                cursor.execute('''
                    UPDATE rate_limits 
                    SET requests_count = ?, window_start = ?
                    WHERE api_key = ?
                ''', (requests_count + 1, window_start.isoformat(), api_key))
                
            else:
                # First request
                cursor.execute('''
                    INSERT INTO rate_limits (api_key, requests_count, window_start)
                    VALUES (?, 1, ?)
                ''', (api_key, now.isoformat()))
                requests_count = 0
            
            conn.commit()
            conn.close()
            
            return True, {'remaining': limit - (requests_count + 1)}
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return False, {'error': 'Rate limit check failed'}
    
    def log_usage(self, customer_id: str, api_key: str, endpoint: str, method: str, 
                  response_time_ms: float, status_code: int = 200, success: bool = True):
        """Log API usage"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO usage_logs 
                (customer_id, api_key, endpoint, method, response_time_ms, status_code, success, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (customer_id, api_key, endpoint, method, response_time_ms, status_code, success, 
                 request.remote_addr if 'request' in globals() else 'unknown'))
            
            # Update customer usage count
            cursor.execute('''
                UPDATE customers SET current_usage = current_usage + 1 WHERE customer_id = ?
            ''', (customer_id,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Usage logging failed: {e}")

# =============================================================================
# AUTHENTICATION DECORATOR
# =============================================================================

core = FastPingCore()

def require_api_key(f):
    """Decorator for API key authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        
        # Get API key
        api_key = request.headers.get('Authorization')
        if api_key and api_key.startswith('Bearer '):
            api_key = api_key[7:]
        else:
            api_key = request.args.get('api_key')
        
        if not api_key:
            return jsonify({'error': 'API key required'}), 401
        
        # Validate API key
        is_valid, customer_info = core.validate_api_key(api_key)
        if not is_valid:
            return jsonify({'error': 'Invalid API key'}), 401
        
        # Check rate limits
        rate_ok, rate_info = core.check_rate_limit(api_key, customer_info['plan_type'])
        if not rate_ok:
            return jsonify(rate_info), 429
        
        # Store in request context
        request.customer_info = customer_info
        request.api_key = api_key
        request.start_time = start_time
        
        # Execute endpoint
        result = f(*args, **kwargs)
        
        # Log usage
        response_time = (time.time() - start_time) * 1000
        status_code = result.status_code if hasattr(result, 'status_code') else 200
        
        core.log_usage(
            customer_info['customer_id'], api_key, request.endpoint,
            request.method, response_time, status_code, status_code < 400
        )
        
        return result
    
    return decorated_function

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/v1/ping', methods=['GET'])
@require_api_key
def api_ping():
    """Ultra-fast ping"""
    return jsonify({
        'status': 'success',
        'message': 'pong',
        'timestamp': time.time(),
        'response_time_ms': (time.time() - request.start_time) * 1000,
        'server': 'FastPing.It'
    })

@app.route('/api/v1/test', methods=['GET', 'POST'])
@require_api_key
def api_test():
    """Full request analysis"""
    return jsonify({
        'status': 'success',
        'method': request.method,
        'headers': dict(request.headers),
        'client_ip': request.remote_addr,
        'data_received': request.get_json() if request.is_json else dict(request.form),
        'customer_plan': request.customer_info['plan_type'],
        'processing_time_ms': (time.time() - request.start_time) * 1000,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/v1/proxy', methods=['GET', 'POST'])
@require_api_key
def api_proxy():
    """Proxy requests to external URLs"""
    if request.customer_info['plan_type'] == 'basic':
        return jsonify({'error': 'Proxy requires Premium plan or higher'}), 403
    
    target_url = request.args.get('url') or (request.get_json() or {}).get('url')
    if not target_url:
        return jsonify({'error': 'Missing target URL'}), 400
    
    try:
        # Forward the request
        headers = dict(request.headers)
        headers.pop('Authorization', None)
        headers.pop('Host', None)
        
        response = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            timeout=30
        )
        
        return jsonify({
            'status': 'success',
            'target_url': target_url,
            'status_code': response.status_code,
            'response_headers': dict(response.headers),
            'content': response.text[:1000] + '...' if len(response.text) > 1000 else response.text,
            'content_length': len(response.content),
            'processing_time_ms': (time.time() - request.start_time) * 1000
        })
        
    except Exception as e:
        return jsonify({'error': f'Proxy failed: {str(e)}'}), 500

@app.route('/api/v1/stats', methods=['GET'])
@require_api_key
def api_stats():
    """Get customer usage statistics"""
    customer_id = request.customer_info['customer_id']
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get usage stats for last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_requests,
                AVG(response_time_ms) as avg_response_time,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_requests
            FROM usage_logs 
            WHERE customer_id = ? AND timestamp > ?
        ''', (customer_id, thirty_days_ago))
        
        stats = cursor.fetchone()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'customer_id': customer_id,
            'plan': request.customer_info['plan_type'],
            'monthly_quota': request.customer_info['monthly_quota'],
            'current_usage': request.customer_info['current_usage'],
            'stats_30d': {
                'total_requests': stats[0] or 0,
                'avg_response_time_ms': round(stats[1] or 0, 2),
                'successful_requests': stats[2] or 0,
                'success_rate': round((stats[2] or 0) / max(stats[0] or 1, 1) * 100, 2)
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Stats failed: {str(e)}'}), 500

# =============================================================================
# PAYPAL WEBHOOK HANDLER
# =============================================================================

@app.route('/webhook/paypal', methods=['POST'])
def paypal_webhook():
    """Handle PayPal payment notifications"""
    try:
        webhook_data = request.get_json()
        event_type = webhook_data.get('event_type')
        resource = webhook_data.get('resource', {})
        
        logger.info(f"PayPal webhook received: {event_type}")
        
        if event_type in ['PAYMENT.SALE.COMPLETED', 'BILLING.SUBSCRIPTION.ACTIVATED']:
            # Extract customer info from PayPal data
            payer_info = resource.get('payer_info', {}) or resource.get('subscriber', {})
            email = payer_info.get('email_address') or payer_info.get('email')
            payment_id = resource.get('id')
            
            if email and payment_id:
                # Determine plan based on amount (rough logic)
                amount = float(resource.get('amount', {}).get('total', 0))
                if amount >= 299:
                    plan_type = 'enterprise'
                elif amount >= 99:
                    plan_type = 'premium'
                else:
                    plan_type = 'basic'
                
                # Create customer account
                success, result = core.create_customer(email, plan_type, payment_id)
                
                if success:
                    logger.info(f"Auto-created customer: {email} -> {plan_type}")
                    
                    # Send welcome email (simple version)
                    threading.Thread(
                        target=send_welcome_email, 
                        args=(email, result['api_key'], plan_type),
                        daemon=True
                    ).start()
                    
                    return jsonify({'status': 'success', 'customer_created': True})
                else:
                    logger.error(f"Failed to create customer: {result}")
        
        return jsonify({'status': 'processed'})
        
    except Exception as e:
        logger.error(f"PayPal webhook failed: {e}")
        return jsonify({'error': 'Webhook processing failed'}), 500

def send_welcome_email(email: str, api_key: str, plan_type: str):
    """Send welcome email to new customer"""
    try:
        # Simple email (you'd configure SMTP settings)
        subject = f"Welcome to FastPing.It - Your {plan_type.title()} Plan is Active!"
        
        message = f"""
Welcome to FastPing.It!

Your {plan_type.title()} plan is now active and ready to use.

API Key: {api_key}
API Endpoint: https://fastping.it/api/v1/

Quick test:
curl -H "Authorization: Bearer {api_key}" https://fastping.it/api/v1/ping

Documentation: https://fastping.it/docs

Need help? Reply to this email.

Welcome aboard!
The FastPing.It Team
        """
        
        # You'd implement actual SMTP here
        logger.info(f"Welcome email prepared for {email}")
        
    except Exception as e:
        logger.error(f"Welcome email failed: {e}")

# =============================================================================
# WEB PAGES
# =============================================================================

@app.route('/')
def index():
    return render_template_string(open('templates/index.html').read() if os.path.exists('templates/index.html') else """
    <h1>FastPing.It</h1>
    <p>API is running! Check /api/v1/ping</p>
    <p>Admin: <a href="/admin/stats">Stats</a></p>
    """)

@app.route('/admin/stats')
def admin_stats():
    """Simple admin dashboard"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get basic stats
        cursor.execute('SELECT COUNT(*) FROM customers')
        total_customers = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM usage_logs WHERE timestamp > ?', 
                      [(datetime.now() - timedelta(hours=24)).isoformat()])
        requests_24h = cursor.fetchone()[0]
        
        cursor.execute('SELECT plan_type, COUNT(*) FROM customers GROUP BY plan_type')
        plan_breakdown = cursor.fetchall()
        
        conn.close()
        
        return f"""
        <h1>FastPing.It Admin</h1>
        <h2>Quick Stats</h2>
        <p>Total Customers: {total_customers}</p>
        <p>Requests (24h): {requests_24h}</p>
        <h3>Plans:</h3>
        <ul>
        {''.join([f'<li>{plan}: {count}</li>' for plan, count in plan_breakdown])}
        </ul>
        <p><a href="/admin/customers">View Customers</a></p>
        """
        
    except Exception as e:
        return f"Error: {e}"

@app.route('/admin/customers')
def admin_customers():
    """List all customers"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT customer_id, email, plan_type, status, current_usage, created_at
            FROM customers ORDER BY created_at DESC LIMIT 50
        ''')
        
        customers = cursor.fetchall()
        conn.close()
        
        html = "<h1>Recent Customers</h1><table border='1'>"
        html += "<tr><th>ID</th><th>Email</th><th>Plan</th><th>Status</th><th>Usage</th><th>Created</th></tr>"
        
        for customer in customers:
            html += f"<tr><td>{customer[0][:12]}...</td><td>{customer[1]}</td><td>{customer[2]}</td><td>{customer[3]}</td><td>{customer[4]}</td><td>{customer[5][:19]}</td></tr>"
        
        html += "</table>"
        return html
        
    except Exception as e:
        return f"Error: {e}"

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/health')
def health_check():
    """System health check"""
    try:
        # Test database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM customers')
        customer_count = cursor.fetchone()[0]
        conn.close()
        
        # Test Redis if available
        redis_status = "connected" if REDIS_AVAILABLE else "unavailable"
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected',
            'redis': redis_status,
            'customers': customer_count,
            'version': '1.0.0'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# =============================================================================
# STARTUP
# =============================================================================

if __name__ == '__main__':
    logger.info("Starting FastPing.It Master Application")
    
    # Initialize database
    init_master_database()
    
    # Create test customer if none exist
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM customers')
        if cursor.fetchone()[0] == 0:
            success, result = core.create_customer('test@fastping.it', 'premium', 'test_payment_123')
            if success:
                logger.info(f"Test customer created with API key: {result['api_key']}")
        conn.close()
    except Exception as e:
        logger.error(f"Test customer creation failed: {e}")
    
    logger.info("FastPing.It is ready!")
    logger.info("Admin dashboard: http://localhost:9876/admin/stats")
    logger.info("Health check: http://localhost:9876/health")
    logger.info("API endpoint: http://localhost:9876/api/v1/ping")
    
    app.run(host='0.0.0.0', port=9876, debug=True)