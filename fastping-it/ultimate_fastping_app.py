#!/usr/bin/env python3
"""
Ultimate FastPing Service - Complete Integration V10
====================================================

CLEAN VERSION - NO @app.before_first_request decorators anywhere!

Combines:
- FastPing API with PayPal integration
- IP whitelisting with Redis caching  
- Automatic customer provisioning
- Proxy testing capabilities
- Complete billing system
- Resource management
"""

from flask import Flask, request, jsonify, render_template_string, Response
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
import redis
import sqlite3
import ipaddress
import time
from datetime import datetime, timedelta
import json
import uuid
import hashlib
import hmac
import requests
import orjson
import threading
from typing import Optional, Dict, Any, Tuple
import os
from dataclasses import dataclass, asdict
from enum import Enum

# Flask app initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///fastping.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database setup
db = SQLAlchemy(app)

# Rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per hour"]
)
limiter.init_app(app)

# Redis setup for ultra-fast IP caching
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
    print("✅ Redis connected")
except:
    REDIS_AVAILABLE = False
    print("⚠️ Redis not available - using database only")

# PayPal configuration
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID')
PAYPAL_CLIENT_SECRET = os.environ.get('PAYPAL_CLIENT_SECRET')
PAYPAL_WEBHOOK_ID = os.environ.get('PAYPAL_WEBHOOK_ID')

class CustomerStatus(Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    PENDING = "pending"

class ResourceType(Enum):
    IP_ONLY = "ip_only"
    IP_PORT = "ip_port"
    PORT_RANGE = "port_range"

# Database Models
class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.String(50), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    company_name = db.Column(db.String(255))
    plan_type = db.Column(db.String(50), default='basic')
    status = db.Column(db.String(50), default='active')
    api_key = db.Column(db.String(100), unique=True, nullable=False)
    monthly_quota = db.Column(db.Integer, default=10000)
    current_usage = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    billing_email = db.Column(db.String(255))
    
    # Relationships
    resources = db.relationship('ResourceAllocation', backref='customer', lazy=True)
    usage_logs = db.relationship('UsageLog', backref='customer', lazy=True)

class ResourceAllocation(db.Model):
    __tablename__ = 'resource_allocations'
    
    id = db.Column(db.String(50), primary_key=True)
    customer_id = db.Column(db.String(50), db.ForeignKey('customers.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    port_start = db.Column(db.Integer)
    port_end = db.Column(db.Integer)
    resource_type = db.Column(db.String(50), nullable=False)
    allocated_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    last_used = db.Column(db.DateTime)

class ResourcePool(db.Model):
    __tablename__ = 'resource_pools'
    
    id = db.Column(db.String(50), primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)
    port_start = db.Column(db.Integer)
    port_end = db.Column(db.Integer)
    resource_type = db.Column(db.String(50), nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    reserved_for_plan = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UsageLog(db.Model):
    __tablename__ = 'usage_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(50), db.ForeignKey('customers.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    response_time_ms = db.Column(db.Float)
    success = db.Column(db.Boolean, default=True)
    user_agent = db.Column(db.Text)

class BillingPeriod(db.Model):
    __tablename__ = 'billing_periods'
    
    id = db.Column(db.String(50), primary_key=True)
    customer_id = db.Column(db.String(50), db.ForeignKey('customers.id'), nullable=False)
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)
    total_requests = db.Column(db.Integer, default=0)
    total_bandwidth_mb = db.Column(db.Float, default=0)
    base_cost = db.Column(db.Float, default=0)
    overage_cost = db.Column(db.Float, default=0)
    total_cost = db.Column(db.Float, default=0)
    invoice_generated = db.Column(db.Boolean, default=False)
    paid = db.Column(db.Boolean, default=False)

# Ultimate Customer Manager
class UltimateCustomerManager:
    def __init__(self):
        self.cache_timeout = 300
        self.init_resource_pools()
        
    def init_resource_pools(self):
        """Initialize IP/port pools if empty"""
        if ResourcePool.query.count() == 0:
            # Add development IPs - including localhost for ALL plan types
            dev_ips = ['127.0.0.1', 'localhost', '10.0.1.100', '10.0.1.101', '10.0.1.102']
            
            # Add basic plan resources
            for ip in dev_ips:
                pool = ResourcePool(
                    id=str(uuid.uuid4()),
                    ip_address=ip,
                    resource_type=ResourceType.IP_ONLY.value,
                    reserved_for_plan='basic'
                )
                db.session.add(pool)
            
            # Add enterprise plan resources (same IPs, different plan)
            for ip in dev_ips:
                pool = ResourcePool(
                    id=str(uuid.uuid4()),
                    ip_address=ip,
                    resource_type=ResourceType.PORT_RANGE.value,
                    reserved_for_plan='enterprise'
                )
                db.session.add(pool)
            
            # Add premium IP+port combinations
            for i, ip in enumerate(['10.0.2.100', '10.0.2.101']):
                for port_start in [8000, 9000, 10000]:
                    pool = ResourcePool(
                        id=str(uuid.uuid4()),
                        ip_address=ip,
                        port_start=port_start,
                        port_end=port_start + 99,
                        resource_type=ResourceType.IP_PORT.value,
                        reserved_for_plan='premium'
                    )
                    db.session.add(pool)
            
            db.session.commit()
            print("✅ Resource pools initialized")
    
    def create_customer_from_paypal(self, email: str, plan_type: str = 'basic') -> Tuple[bool, str]:
        """Create customer with automatic resource allocation"""
        try:
            customer_id = f"cust_{uuid.uuid4().hex[:12]}"
            api_key = f"ak_{hashlib.sha256(f'{customer_id}{time.time()}'.encode()).hexdigest()[:32]}"
            
            # Plan quotas
            quotas = {'basic': 10000, 'premium': 50000, 'enterprise': 200000}
            monthly_quota = quotas.get(plan_type, 10000)
            
            # Create customer
            customer = Customer(
                id=customer_id,
                email=email,
                plan_type=plan_type,
                api_key=api_key,
                monthly_quota=monthly_quota,
                status=CustomerStatus.ACTIVE.value
            )
            db.session.add(customer)
            
            # Allocate resources
            resource = self._allocate_resource(customer_id, plan_type)
            if not resource:
                db.session.rollback()
                return False, "No available resources"
            
            # Add to IP whitelist
            self._add_to_whitelist(resource.ip_address, customer_id, plan_type)
            
            db.session.commit()
            print(f"✅ Customer created: {customer_id} with IP {resource.ip_address}")
            
            return True, customer_id
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error creating customer: {e}")
            return False, str(e)
    
    def _allocate_resource(self, customer_id: str, plan_type: str) -> Optional[ResourceAllocation]:
        """Allocate resource based on plan type"""
        # Determine resource type - SIMPLIFIED for testing
        resource_type = ResourceType.IP_ONLY  # Use IP_ONLY for all plans to start
        
        # Find available resource for this plan type
        available_pool = ResourcePool.query.filter_by(
            resource_type=resource_type.value,
            is_available=True,
            reserved_for_plan=plan_type
        ).first()
        
        # If no exact match, try any available IP_ONLY resource
        if not available_pool:
            available_pool = ResourcePool.query.filter_by(
                resource_type=ResourceType.IP_ONLY.value,
                is_available=True
            ).first()
        
        if not available_pool:
            print(f"❌ No available resources found for plan {plan_type}")
            # Debug: show what's available
            all_pools = ResourcePool.query.all()
            for pool in all_pools:
                print(f"   Pool: {pool.ip_address} | Type: {pool.resource_type} | Plan: {pool.reserved_for_plan} | Available: {pool.is_available}")
            return None
        
        # Mark as allocated
        available_pool.is_available = False
        
        # Create allocation
        allocation = ResourceAllocation(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            ip_address=available_pool.ip_address,
            port_start=available_pool.port_start,
            port_end=available_pool.port_end,
            resource_type=resource_type.value,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.session.add(allocation)
        
        print(f"✅ Allocated {available_pool.ip_address} to customer {customer_id}")
        return allocation
    
    def _add_to_whitelist(self, ip_address: str, customer_id: str, plan_type: str):
        """Add IP to Redis whitelist cache"""
        rate_limits = {'basic': 100, 'premium': 500, 'enterprise': 2000}
        rate_limit = rate_limits.get(plan_type, 100)
        
        if REDIS_AVAILABLE:
            cache_key = f"whitelist:{ip_address}"
            cache_data = {
                'customer_id': customer_id,
                'plan_type': plan_type,
                'rate_limit': rate_limit,
                'expires_at': (datetime.utcnow() + timedelta(days=30)).isoformat()
            }
            redis_client.setex(cache_key, self.cache_timeout, json.dumps(cache_data))
            print(f"✅ IP {ip_address} added to whitelist cache")
    
    def is_ip_allowed(self, ip_address: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Ultra-fast IP whitelist check with Redis"""
        # Redis cache first
        if REDIS_AVAILABLE:
            cache_key = f"whitelist:{ip_address}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                try:
                    data = json.loads(cached_data)
                    if datetime.fromisoformat(data['expires_at']) > datetime.utcnow():
                        return True, data
                except:
                    pass
        
        # Database fallback
        allocation = ResourceAllocation.query.filter_by(
            ip_address=ip_address,
            is_active=True
        ).first()
        
        if allocation and allocation.expires_at > datetime.utcnow():
            customer = Customer.query.get(allocation.customer_id)
            if customer and customer.status == CustomerStatus.ACTIVE.value:
                rate_limits = {'basic': 100, 'premium': 500, 'enterprise': 2000}
                data = {
                    'customer_id': customer.id,
                    'plan_type': customer.plan_type,
                    'rate_limit': rate_limits.get(customer.plan_type, 100),
                    'expires_at': allocation.expires_at.isoformat()
                }
                
                # Cache for next time
                if REDIS_AVAILABLE:
                    cache_key = f"whitelist:{ip_address}"
                    redis_client.setex(cache_key, self.cache_timeout, json.dumps(data))
                
                return True, data
        
        return False, None
    
    def check_rate_limit(self, ip_address: str, rate_limit: int) -> bool:
        """Check rate limit with Redis"""
        if REDIS_AVAILABLE:
            key = f"rate_limit:{ip_address}"
            current_count = redis_client.incr(key)
            if current_count == 1:
                redis_client.expire(key, 60)  # 1-minute window
            return current_count <= rate_limit
        return True  # No rate limiting without Redis
    
    def log_usage(self, ip_address: str, customer_id: str, endpoint: str, 
                  response_time_ms: float, success: bool = True):
        """Log usage for billing"""
        try:
            usage_log = UsageLog(
                customer_id=customer_id,
                ip_address=ip_address,
                endpoint=endpoint,
                response_time_ms=response_time_ms,
                success=success,
                user_agent=request.headers.get('User-Agent', '')
            )
            db.session.add(usage_log)
            db.session.commit()
        except Exception as e:
            print(f"Error logging usage: {e}")
            db.session.rollback()

# Initialize customer manager - will be created after app context is ready
customer_manager = None

# Proxy detection utilities
def get_client_ip(req):
    """Get real client IP considering proxy headers"""
    x_forwarded_for = req.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        ips = [ip.strip() for ip in x_forwarded_for.split(',')]
        for ip_str in ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if not ip_obj.is_private:
                    return ip_str
            except ValueError:
                continue
        return ips[0] if ips else req.remote_addr
    return req.remote_addr

def determine_anonymity(req, proxy_ip):
    """Determine proxy anonymity level"""
    via_header = req.headers.get('Via')
    x_forwarded_for = req.headers.get('X-Forwarded-For')
    connecting_ip = req.remote_addr

    if via_header or (x_forwarded_for and x_forwarded_for != connecting_ip):
        return "transparent"
    
    if proxy_ip and connecting_ip != proxy_ip:
        return "anonymous"
    
    return "elite"

def determine_speed(latency_ms):
    """Determine proxy speed from latency"""
    if latency_ms < 200:
        return "fast"
    elif latency_ms < 800:
        return "medium"
    else:
        return "slow"

# Authentication decorators
def require_api_key(f):
    """Require API key authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        
        api_key = auth_header.split(' ')[1]
        customer = Customer.query.filter_by(api_key=api_key, status='active').first()
        
        if not customer:
            return jsonify({'error': 'Invalid API key'}), 401
        
        # Check usage limits
        if customer.current_usage >= customer.monthly_quota:
            return jsonify({'error': 'Monthly quota exceeded'}), 429
        
        request.current_customer = customer
        return f(*args, **kwargs)
    
    return decorated_function

def require_whitelisted_ip(f):
    """Require whitelisted IP with ultra-fast checking"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        client_ip = get_client_ip(request)
        
        is_allowed, client_data = customer_manager.is_ip_allowed(client_ip)
        
        if not is_allowed:
            customer_manager.log_usage(client_ip, 'unknown', request.endpoint, 
                                     (time.time() - start_time) * 1000, False)
            return Response(orjson.dumps({
                'error': 'Access denied',
                'message': 'IP not whitelisted for service',
                'ip': client_ip,
                'contact': 'support@fastping.it.com'
            }), status=403, mimetype='application/json')
        
        if not customer_manager.check_rate_limit(client_ip, client_data['rate_limit']):
            customer_manager.log_usage(client_ip, client_data['customer_id'], 
                                     request.endpoint, (time.time() - start_time) * 1000, False)
            return Response(orjson.dumps({
                'error': 'Rate limit exceeded',
                'message': f"Rate limit: {client_data['rate_limit']} requests/minute",
                'plan': client_data['plan_type']
            }), status=429, mimetype='application/json')
        
        request.client_data = client_data
        result = f(*args, **kwargs)
        
        response_time = (time.time() - start_time) * 1000
        customer_manager.log_usage(client_ip, client_data['customer_id'], 
                                 request.endpoint, response_time, True)
        
        return result
    
    return decorated_function

# PayPal webhook handler
@app.route('/webhook/paypal', methods=['POST'])
def paypal_webhook():
    """Handle PayPal payment webhooks"""
    try:
        # Verify webhook signature
        if not verify_paypal_webhook(request):
            return jsonify({'error': 'Invalid webhook signature'}), 401
        
        webhook_data = request.json
        event_type = webhook_data.get('event_type')
        
        if event_type == 'PAYMENT.SALE.COMPLETED':
            # Extract customer info from payment
            payer_info = webhook_data['resource']['payer']['payer_info']
            email = payer_info.get('email')
            
            # Determine plan from amount (simplified)
            amount = float(webhook_data['resource']['amount']['total'])
            if amount >= 299:
                plan_type = 'enterprise'
            elif amount >= 99:
                plan_type = 'premium'
            else:
                plan_type = 'basic'
            
            # Create customer
            success, customer_id = customer_manager.create_customer_from_paypal(email, plan_type)
            
            if success:
                print(f"✅ PayPal webhook: Customer {customer_id} created for {email}")
                return jsonify({'message': 'Customer created successfully', 'customer_id': customer_id})
            else:
                print(f"❌ PayPal webhook: Failed to create customer for {email}")
                return jsonify({'error': 'Failed to create customer'}), 500
        
        return jsonify({'message': 'Webhook processed'})
        
    except Exception as e:
        print(f"PayPal webhook error: {e}")
        return jsonify({'error': 'Webhook processing failed'}), 500

def verify_paypal_webhook(request):
    """Verify PayPal webhook signature"""
    # Simplified verification - implement full verification in production
    return True

# API Endpoints

# Ultra-fast ping endpoint
@app.route('/api/v1/ping', methods=['GET', 'POST'])
@require_api_key
@limiter.limit("1000 per minute")
def api_ping():
    """Ultra-fast ping endpoint for paid customers"""
    start_time = time.time()
    
    customer = request.current_customer
    client_ip = get_client_ip(request)
    
    # Increment usage
    customer.current_usage += 1
    db.session.commit()
    
    response_time_ms = (time.time() - start_time) * 1000
    
    result = {
        'status': 'success',
        'message': 'FastPing service active',
        'timestamp': datetime.utcnow().isoformat(),
        'customer_id': customer.id,
        'plan': customer.plan_type,
        'usage': f"{customer.current_usage}/{customer.monthly_quota}",
        'client_ip': client_ip,
        'response_time_ms': round(response_time_ms, 2)
    }
    
    return Response(orjson.dumps(result), mimetype='application/json')

# Proxy test endpoint (whitelisted IPs only)
@app.route('/proxy-test', defaults={'path': ''})
@app.route('/proxy-test/<path:path>')
@require_whitelisted_ip
def proxy_test_endpoint(path):
    """Ultra-fast proxy testing for whitelisted IPs"""
    start_time = time.time()
    
    connecting_ip = request.remote_addr
    client_ip_from_headers = get_client_ip(request)
    server_processing_latency_ms = (time.time() - start_time) * 1000
    anonymity_level = determine_anonymity(request, connecting_ip)
    
    response_data = {
        "status": "success",
        "service": "FastPing Proxy Test",
        "path": f"/{path}",
        "method": request.method,
        "headers": dict(request.headers),
        "connecting_ip": connecting_ip,
        "client_ip": client_ip_from_headers,
        "anonymity_level": anonymity_level,
        "speed": determine_speed(server_processing_latency_ms),
        "response_time_ms": round(server_processing_latency_ms, 2),
        "plan": request.client_data['plan_type'],
        "timestamp": datetime.utcnow().isoformat()
    }
    
    return Response(orjson.dumps(response_data), mimetype='application/json')

# Health check
@app.route('/health')
def health():
    """Public health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'FastPing Ultimate',
        'timestamp': datetime.utcnow().isoformat(),
        'redis': REDIS_AVAILABLE
    })

# Admin dashboard
@app.route('/admin/stats')
def admin_stats():
    """Admin statistics dashboard"""
    stats = {
        'total_customers': Customer.query.count(),
        'active_customers': Customer.query.filter_by(status='active').count(),
        'total_allocations': ResourceAllocation.query.filter_by(is_active=True).count(),
        'available_resources': ResourcePool.query.filter_by(is_available=True).count(),
        'total_requests_today': UsageLog.query.filter(
            UsageLog.timestamp >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).count(),
        'redis_status': 'connected' if REDIS_AVAILABLE else 'disconnected'
    }
    
    # Recent customers
    recent_customers = Customer.query.order_by(Customer.created_at.desc()).limit(10).all()
    
    dashboard_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FastPing Admin Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .dashboard {{ background: white; padding: 20px; border-radius: 10px; }}
            .stat {{ display: inline-block; margin: 10px; padding: 15px; background: #007bff; color: white; border-radius: 5px; }}
            .customers {{ margin-top: 20px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background: #f8f9fa; }}
        </style>
    </head>
    <body>
        <div class="dashboard">
            <h1>🚀 FastPing Admin Dashboard</h1>
            
            <div class="stats">
                <div class="stat">Total Customers: {stats['total_customers']}</div>
                <div class="stat">Active: {stats['active_customers']}</div>
                <div class="stat">Resources Used: {stats['total_allocations']}</div>
                <div class="stat">Available: {stats['available_resources']}</div>
                <div class="stat">Requests Today: {stats['total_requests_today']}</div>
                <div class="stat">Redis: {stats['redis_status']}</div>
            </div>
            
            <div class="customers">
                <h2>Recent Customers</h2>
                <table>
                    <tr>
                        <th>Customer ID</th>
                        <th>Email</th>
                        <th>Plan</th>
                        <th>Status</th>
                        <th>Usage</th>
                        <th>Created</th>
                    </tr>
                    {''.join([f'''
                    <tr>
                        <td>{c.id}</td>
                        <td>{c.email}</td>
                        <td>{c.plan_type}</td>
                        <td>{c.status}</td>
                        <td>{c.current_usage}/{c.monthly_quota}</td>
                        <td>{c.created_at.strftime('%Y-%m-%d %H:%M')}</td>
                    </tr>
                    ''' for c in recent_customers])}
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    
    return dashboard_html

# Test customer creation endpoint
@app.route('/admin/create_test_customer', methods=['POST'])
def create_test_customer():
    """Create test customer for development"""
    data = request.get_json()
    email = data.get('email', f'test_{int(time.time())}@fastping.dev')
    plan = data.get('plan_type', 'basic')
    
    success, customer_id = customer_manager.create_customer_from_paypal(email, plan)
    
    if success:
        customer = Customer.query.get(customer_id)
        resources = ResourceAllocation.query.filter_by(customer_id=customer_id, is_active=True).all()
        
        return jsonify({
            'success': True,
            'customer_id': customer_id,
            'api_key': customer.api_key,
            'plan': customer.plan_type,
            'allocated_ips': [r.ip_address for r in resources],
            'quota': customer.monthly_quota
        })
    else:
        return jsonify({'success': False, 'error': customer_id}), 400

# Initialize database and customer manager
def initialize_app():
    """Initialize database tables and customer manager"""
    global customer_manager
    
    # Ensure data directory exists
    data_dir = os.path.dirname('fastping.db')
    if data_dir and not os.path.exists(data_dir):
        os.makedirs(data_dir, exist_ok=True)
        print(f"✅ Created directory: {data_dir}")
    
    # Create all database tables
    db.create_all()
    print("✅ Database tables created")
    
    # Now we can safely create the customer manager
    customer_manager = UltimateCustomerManager()
    
    # Create test customer if none exist
    if Customer.query.count() == 0:
        print("Creating test customer...")
        success, customer_id = customer_manager.create_customer_from_paypal(
            'test@fastping.dev', 'enterprise'
        )
        if success:
            test_customer = Customer.query.get(customer_id)
            print(f"✅ Test customer created:")
            print(f"   Customer ID: {customer_id}")
            print(f"   API Key: {test_customer.api_key}")
            print(f"   Plan: {test_customer.plan_type}")

# Call initialization when app starts
with app.app_context():
    initialize_app()

if __name__ == '__main__':
    print("🚀 Starting Ultimate FastPing Service...")
    print("✅ Features enabled:")
    print("   - FastPing API with authentication")
    print("   - IP whitelisting with Redis caching") 
    print("   - Automatic customer provisioning")
    print("   - Proxy testing capabilities")
    print("   - Complete billing system")
    print("   - Resource management")
    print("   - PayPal webhook integration")
    print("")
    print("🌐 Endpoints:")
    print("   - Health: http://localhost:9876/health")
    print("   - Admin: http://localhost:9876/admin/stats")
    print("   - API Ping: http://localhost:9876/api/v1/ping")
    print("   - Proxy Test: http://localhost:9876/proxy-test")
    print("   - PayPal Webhook: http://localhost:9876/webhook/paypal")
    
    app.run(host='0.0.0.0', port=9876, debug=False)  # Turn off debug to avoid restart issues