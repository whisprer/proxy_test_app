"""
Complete API Access System for FastPing.It
==========================================

Provides programmatic access to your proxy service with:
- API key authentication
- Rate limiting per plan
- Usage tracking for billing
- Multiple endpoint types
- Real-time monitoring
"""

from flask import Flask, request, jsonify, g
from functools import wraps
import time
import hashlib
import hmac
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
import requests
from typing import Dict, Optional, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APIManager:
    def __init__(self, whitelist_manager, customer_manager):
        self.whitelist_manager = whitelist_manager
        self.customer_manager = customer_manager
        self.init_api_database()
        
    def init_api_database(self):
        """Initialize API-specific database tables"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        # API keys table (extend existing customers table)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                api_key TEXT UNIQUE NOT NULL,
                key_name TEXT,
                permissions TEXT DEFAULT 'basic',
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                expires_at TIMESTAMP,
                total_requests INTEGER DEFAULT 0,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # API usage tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_usage (
                usage_id TEXT PRIMARY KEY,
                api_key TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                request_size INTEGER DEFAULT 0,
                response_size INTEGER DEFAULT 0,
                response_time_ms REAL,
                status_code INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                billing_processed BOOLEAN DEFAULT 0,
                FOREIGN KEY (api_key) REFERENCES api_keys (api_key)
            )
        ''')
        
        # API rate limiting
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_rate_limits (
                api_key TEXT PRIMARY KEY,
                requests_count INTEGER DEFAULT 0,
                window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                daily_count INTEGER DEFAULT 0,
                daily_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # API endpoints configuration
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_endpoints (
                endpoint_id TEXT PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                method TEXT NOT NULL,
                description TEXT,
                required_plan TEXT DEFAULT 'basic',
                rate_limit_override INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Create default API endpoints
        self.create_default_endpoints()
    
    def create_default_endpoints(self):
        """Create default API endpoints"""
        endpoints = [
            {
                'path': '/api/v1/ping',
                'method': 'GET',
                'description': 'Basic connectivity test - fastest response possible',
                'required_plan': 'basic',
                'rate_limit_override': None
            },
            {
                'path': '/api/v1/test',
                'method': 'GET,POST',
                'description': 'Full proxy test with headers and data analysis',
                'required_plan': 'basic',
                'rate_limit_override': None
            },
            {
                'path': '/api/v1/proxy',
                'method': 'GET,POST,PUT,DELETE',
                'description': 'Full proxy request to any destination',
                'required_plan': 'premium',
                'rate_limit_override': None
            },
            {
                'path': '/api/v1/stats',
                'method': 'GET',
                'description': 'Get your usage statistics and performance metrics',
                'required_plan': 'basic',
                'rate_limit_override': 10  # Lower rate limit for stats
            },
            {
                'path': '/api/v1/batch',
                'method': 'POST',
                'description': 'Process multiple requests in a single call',
                'required_plan': 'enterprise',
                'rate_limit_override': 5
            }
        ]
        
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        for endpoint in endpoints:
            endpoint_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT OR REPLACE INTO api_endpoints 
                (endpoint_id, path, method, description, required_plan, rate_limit_override)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (endpoint_id, endpoint['path'], endpoint['method'], 
                 endpoint['description'], endpoint['required_plan'], 
                 endpoint['rate_limit_override']))
        
        conn.commit()
        conn.close()
    
    def generate_api_key(self, customer_id: str, key_name: str = None) -> str:
        """Generate new API key for customer"""
        try:
            # Generate secure API key
            api_key = f"fpk_{uuid.uuid4().hex}"
            key_id = str(uuid.uuid4())
            
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Check if customer exists
            cursor.execute('SELECT plan_type FROM customers WHERE customer_id = ?', (customer_id,))
            result = cursor.fetchone()
            
            if not result:
                conn.close()
                return None
            
            plan_type = result[0]
            
            # Insert API key
            cursor.execute('''
                INSERT INTO api_keys 
                (key_id, customer_id, api_key, key_name, permissions)
                VALUES (?, ?, ?, ?, ?)
            ''', (key_id, customer_id, api_key, key_name or 'Default API Key', plan_type))
            
            conn.commit()
            conn.close()
            
            return api_key
            
        except Exception as e:
            logger.error(f"Error generating API key: {e}")
            return None
    
    def validate_api_key(self, api_key: str) -> Tuple[bool, Optional[Dict]]:
        """Validate API key and return customer info"""
        try:
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT ak.customer_id, ak.permissions, ak.is_active, 
                       c.plan_type, c.status, ak.expires_at
                FROM api_keys ak
                JOIN customers c ON ak.customer_id = c.customer_id
                WHERE ak.api_key = ?
            ''', (api_key,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return False, None
            
            customer_id, permissions, is_active, plan_type, status, expires_at = result
            
            # Check if key is active
            if not is_active or status != 'active':
                return False, None
            
            # Check expiration
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at)
                if expires_dt < datetime.now():
                    return False, None
            
            return True, {
                'customer_id': customer_id,
                'permissions': permissions,
                'plan_type': plan_type
            }
            
        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return False, None
    
    def check_rate_limit(self, api_key: str, endpoint: str, plan_type: str) -> Tuple[bool, Dict]:
        """Check if request is within rate limits"""
        try:
            # Get rate limits based on plan
            plan_limits = {
                'basic': {'per_minute': 100, 'per_day': 10000},
                'premium': {'per_minute': 500, 'per_day': 50000},
                'enterprise': {'per_minute': 2000, 'per_day': 200000}
            }
            
            limits = plan_limits.get(plan_type, plan_limits['basic'])
            
            # Check for endpoint-specific overrides
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT rate_limit_override FROM api_endpoints 
                WHERE path = ? AND is_active = 1
            ''', (endpoint,))
            
            override_result = cursor.fetchone()
            if override_result and override_result[0]:
                limits['per_minute'] = override_result[0]
            
            # Get current usage
            cursor.execute('''
                SELECT requests_count, window_start, daily_count, daily_reset
                FROM api_rate_limits WHERE api_key = ?
            ''', (api_key,))
            
            result = cursor.fetchone()
            
            now = datetime.now()
            
            if result:
                requests_count, window_start_str, daily_count, daily_reset_str = result
                window_start = datetime.fromisoformat(window_start_str)
                daily_reset = datetime.fromisoformat(daily_reset_str)
                
                # Check if we need to reset windows
                if now - window_start > timedelta(minutes=1):
                    requests_count = 0
                    window_start = now
                
                if now - daily_reset > timedelta(days=1):
                    daily_count = 0
                    daily_reset = now
                
                # Check limits
                if requests_count >= limits['per_minute']:
                    conn.close()
                    return False, {
                        'error': 'Rate limit exceeded',
                        'limit': limits['per_minute'],
                        'window': 'per_minute',
                        'reset_at': (window_start + timedelta(minutes=1)).isoformat()
                    }
                
                if daily_count >= limits['per_day']:
                    conn.close()
                    return False, {
                        'error': 'Daily limit exceeded',
                        'limit': limits['per_day'],
                        'window': 'per_day',
                        'reset_at': (daily_reset + timedelta(days=1)).isoformat()
                    }
                
                # Update counters
                cursor.execute('''
                    UPDATE api_rate_limits 
                    SET requests_count = ?, window_start = ?, 
                        daily_count = ?, daily_reset = ?
                    WHERE api_key = ?
                ''', (requests_count + 1, window_start.isoformat(),
                     daily_count + 1, daily_reset.isoformat(), api_key))
                
            else:
                # First request for this API key
                cursor.execute('''
                    INSERT INTO api_rate_limits 
                    (api_key, requests_count, window_start, daily_count, daily_reset)
                    VALUES (?, ?, ?, ?, ?)
                ''', (api_key, 1, now.isoformat(), 1, now.isoformat()))
            
            conn.commit()
            conn.close()
            
            return True, {
                'remaining_minute': limits['per_minute'] - (requests_count + 1),
                'remaining_day': limits['per_day'] - (daily_count + 1),
                'reset_minute': (window_start + timedelta(minutes=1)).isoformat() if result else (now + timedelta(minutes=1)).isoformat(),
                'reset_day': (daily_reset + timedelta(days=1)).isoformat() if result else (now + timedelta(days=1)).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return False, {'error': 'Rate limit check failed'}
    
    def log_api_usage(self, api_key: str, customer_id: str, endpoint: str, 
                     method: str, status_code: int, response_time_ms: float,
                     request_size: int = 0, response_size: int = 0):
        """Log API usage for billing and analytics"""
        try:
            usage_id = str(uuid.uuid4())
            
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO api_usage 
                (usage_id, api_key, customer_id, endpoint, method, 
                 ip_address, user_agent, request_size, response_size,
                 response_time_ms, status_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (usage_id, api_key, customer_id, endpoint, method,
                 request.remote_addr, request.headers.get('User-Agent', ''),
                 request_size, response_size, response_time_ms, status_code))
            
            # Update API key last used
            cursor.execute('''
                UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP,
                total_requests = total_requests + 1
                WHERE api_key = ?
            ''', (api_key,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error logging API usage: {e}")

# Flask decorators for API authentication
def require_api_key(required_plan: str = 'basic'):
    """Decorator to require API key authentication"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            api_manager = g.get('api_manager')
            if not api_manager:
                return jsonify({'error': 'API system not initialized'}), 500
            
            start_time = time.time()
            
            # Get API key from header or query parameter
            api_key = request.headers.get('Authorization')
            if api_key and api_key.startswith('Bearer '):
                api_key = api_key[7:]  # Remove 'Bearer ' prefix
            else:
                api_key = request.args.get('api_key')
            
            if not api_key:
                return jsonify({
                    'error': 'API key required',
                    'message': 'Provide API key in Authorization header (Bearer token) or api_key parameter'
                }), 401
            
            # Validate API key
            is_valid, customer_info = api_manager.validate_api_key(api_key)
            if not is_valid:
                return jsonify({
                    'error': 'Invalid API key',
                    'message': 'API key is invalid, expired, or disabled'
                }), 401
            
            # Check plan requirements
            plan_hierarchy = {'basic': 0, 'premium': 1, 'enterprise': 2}
            customer_plan_level = plan_hierarchy.get(customer_info['plan_type'], 0)
            required_plan_level = plan_hierarchy.get(required_plan, 0)
            
            if customer_plan_level < required_plan_level:
                return jsonify({
                    'error': 'Insufficient plan',
                    'message': f'This endpoint requires {required_plan} plan or higher',
                    'current_plan': customer_info['plan_type'],
                    'upgrade_url': 'https://fastping.it/pricing'
                }), 403
            
            # Check rate limits
            endpoint_path = request.endpoint or request.path
            rate_ok, rate_info = api_manager.check_rate_limit(
                api_key, endpoint_path, customer_info['plan_type']
            )
            
            if not rate_ok:
                response = jsonify(rate_info)
                response.status_code = 429
                response.headers['Retry-After'] = '60'
                return response
            
            # Store info in g for use in endpoint
            g.api_key = api_key
            g.customer_info = customer_info
            g.rate_info = rate_info
            g.start_time = start_time
            
            # Execute the actual endpoint
            result = f(*args, **kwargs)
            
            # Log usage
            response_time = (time.time() - start_time) * 1000
            status_code = result.status_code if hasattr(result, 'status_code') else 200
            
            api_manager.log_api_usage(
                api_key, customer_info['customer_id'], endpoint_path,
                request.method, status_code, response_time
            )
            
            # Add rate limit headers to response
            if hasattr(result, 'headers'):
                result.headers['X-RateLimit-Remaining-Minute'] = str(rate_info.get('remaining_minute', 0))
                result.headers['X-RateLimit-Remaining-Day'] = str(rate_info.get('remaining_day', 0))
                result.headers['X-RateLimit-Reset-Minute'] = rate_info.get('reset_minute', '')
                result.headers['X-RateLimit-Reset-Day'] = rate_info.get('reset_day', '')
            
            return result
            
        return decorated_function
    return decorator

# API Endpoints
def create_api_endpoints(app, api_manager, whitelist_manager):
    """Create all API endpoints"""
    
    # Store API manager in app context
    @app.before_request
    def before_request():
        g.api_manager = api_manager
    
    @app.route('/api/v1/ping', methods=['GET'])
    @require_api_key('basic')
    def api_ping():
        """Ultra-fast ping endpoint"""
        return jsonify({
            'status': 'success',
            'message': 'pong',
            'timestamp': time.time(),
            'response_time_ms': (time.time() - g.start_time) * 1000,
            'server': 'FastPing.It'
        })
    
    @app.route('/api/v1/test', methods=['GET', 'POST'])
    @require_api_key('basic')
    def api_test():
        """Full proxy test endpoint"""
        start_time = g.start_time
        
        # Analyze the request
        headers_received = dict(request.headers)
        client_ip = request.remote_addr
        method = request.method
        
        # Get any data sent
        request_data = None
        if request.is_json:
            request_data = request.get_json()
        elif request.form:
            request_data = dict(request.form)
        
        response_data = {
            'status': 'success',
            'test_type': 'full_analysis',
            'request_info': {
                'method': method,
                'headers': headers_received,
                'client_ip': client_ip,
                'user_agent': request.headers.get('User-Agent'),
                'content_type': request.headers.get('Content-Type'),
                'content_length': request.headers.get('Content-Length')
            },
            'data_received': request_data,
            'server_info': {
                'server': 'FastPing.It',
                'processing_time_ms': (time.time() - start_time) * 1000,
                'timestamp': datetime.now().isoformat()
            },
            'customer_info': {
                'plan': g.customer_info['plan_type'],
                'remaining_requests_minute': g.rate_info.get('remaining_minute'),
                'remaining_requests_day': g.rate_info.get('remaining_day')
            }
        }
        
        return jsonify(response_data)
    
    @app.route('/api/v1/proxy', methods=['GET', 'POST', 'PUT', 'DELETE'])
    @require_api_key('premium')
    def api_proxy():
        """Full proxy request to external URL"""
        target_url = request.args.get('url') or (request.get_json() or {}).get('url')
        
        if not target_url:
            return jsonify({
                'error': 'Missing target URL',
                'message': 'Provide target URL in "url" parameter or JSON body'
            }), 400
        
        try:
            # Forward the request
            headers = dict(request.headers)
            headers.pop('Host', None)  # Remove host header
            headers.pop('Authorization', None)  # Remove API key
            
            response = requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=request.get_data(),
                params=request.args,
                timeout=30
            )
            
            # Return proxied response
            return jsonify({
                'status': 'success',
                'proxy_response': {
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'content': response.text,
                    'content_length': len(response.content)
                },
                'request_info': {
                    'target_url': target_url,
                    'method': request.method,
                    'processing_time_ms': (time.time() - g.start_time) * 1000
                }
            })
            
        except Exception as e:
            return jsonify({
                'error': 'Proxy request failed',
                'message': str(e),
                'target_url': target_url
            }), 500
    
    @app.route('/api/v1/stats', methods=['GET'])
    @require_api_key('basic')
    def api_stats():
        """Get customer usage statistics"""
        customer_id = g.customer_info['customer_id']
        
        try:
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Get usage stats for last 30 days
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_requests,
                    AVG(response_time_ms) as avg_response_time,
                    COUNT(DISTINCT DATE(timestamp)) as active_days,
                    SUM(request_size + response_size) as total_bytes
                FROM api_usage 
                WHERE customer_id = ? AND timestamp > ?
            ''', (customer_id, thirty_days_ago))
            
            stats = cursor.fetchone()
            
            # Get rate limit status
            cursor.execute('''
                SELECT requests_count, daily_count FROM api_rate_limits 
                WHERE api_key = ?
            ''', (g.api_key,))
            
            rate_data = cursor.fetchone()
            
            conn.close()
            
            return jsonify({
                'status': 'success',
                'customer_id': customer_id,
                'plan': g.customer_info['plan_type'],
                'usage_stats_30d': {
                    'total_requests': stats[0] or 0,
                    'avg_response_time_ms': round(stats[1] or 0, 2),
                    'active_days': stats[2] or 0,
                    'total_bytes_transferred': stats[3] or 0
                },
                'current_limits': {
                    'requests_this_minute': rate_data[0] if rate_data else 0,
                    'requests_today': rate_data[1] if rate_data else 0,
                    'remaining_minute': g.rate_info.get('remaining_minute'),
                    'remaining_day': g.rate_info.get('remaining_day')
                },
                'generated_at': datetime.now().isoformat()
            })
            
        except Exception as e:
            return jsonify({
                'error': 'Failed to get stats',
                'message': str(e)
            }), 500
    
    @app.route('/api/v1/batch', methods=['POST'])
    @require_api_key('enterprise')
    def api_batch():
        """Process multiple requests in batch"""
        batch_data = request.get_json()
        
        if not batch_data or 'requests' not in batch_data:
            return jsonify({
                'error': 'Invalid batch format',
                'message': 'Send JSON with "requests" array'
            }), 400
        
        requests_list = batch_data['requests']
        if len(requests_list) > 10:  # Limit batch size
            return jsonify({
                'error': 'Batch too large',
                'message': 'Maximum 10 requests per batch',
                'received': len(requests_list)
            }), 400
        
        results = []
        
        for i, req_data in enumerate(requests_list):
            try:
                if 'url' not in req_data:
                    results.append({
                        'index': i,
                        'status': 'error',
                        'error': 'Missing URL'
                    })
                    continue
                
                # Process individual request
                response = requests.get(
                    req_data['url'],
                    timeout=10,
                    headers=req_data.get('headers', {})
                )
                
                results.append({
                    'index': i,
                    'status': 'success',
                    'url': req_data['url'],
                    'status_code': response.status_code,
                    'response_time_ms': response.elapsed.total_seconds() * 1000,
                    'content_length': len(response.content)
                })
                
            except Exception as e:
                results.append({
                    'index': i,
                    'status': 'error',
                    'url': req_data.get('url', 'unknown'),
                    'error': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'batch_id': str(uuid.uuid4()),
            'total_requests': len(requests_list),
            'successful_requests': len([r for r in results if r['status'] == 'success']),
            'failed_requests': len([r for r in results if r['status'] == 'error']),
            'results': results,
            'processing_time_ms': (time.time() - g.start_time) * 1000
        })

# Management endpoints for customers
def create_management_endpoints(app, api_manager):
    """Create customer management endpoints"""
    
    @app.route('/api/account/keys', methods=['GET'])
    @require_api_key('basic')
    def list_api_keys():
        """List customer's API keys"""
        customer_id = g.customer_info['customer_id']
        
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT api_key, key_name, created_at, last_used_at, total_requests, is_active
            FROM api_keys WHERE customer_id = ?
        ''', (customer_id,))
        
        keys = []
        for row in cursor.fetchall():
            keys.append({
                'api_key': row[0][:12] + '...' + row[0][-4:],  # Mask the key
                'key_name': row[1],
                'created_at': row[2],
                'last_used_at': row[3],
                'total_requests': row[4],
                'is_active': bool(row[5])
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'api_keys': keys
        })
    
    @app.route('/api/account/keys', methods=['POST'])
    @require_api_key('basic')
    def create_api_key():
        """Create new API key"""
        data = request.get_json() or {}
        key_name = data.get('name', 'API Key')
        
        customer_id = g.customer_info['customer_id']
        new_key = api_manager.generate_api_key(customer_id, key_name)
        
        if new_key:
            return jsonify({
                'status': 'success',
                'api_key': new_key,
                'key_name': key_name,
                'message': 'Store this key securely - it cannot be retrieved again'
            })
        else:
            return jsonify({
                'error': 'Failed to create API key'
            }), 500

# Complete setup function
def setup_api_system(app, whitelist_manager, customer_manager):
    """Setup complete API system"""
    
    # Initialize API manager
    api_manager = APIManager(whitelist_manager, customer_manager)
    
    # Create all endpoints
    create_api_endpoints(app, api_manager, whitelist_manager)
    create_management_endpoints(app, api_manager)
    
    logger.info("🚀 Complete API system initialized!")
    
    return api_manager