"""
Ultra-Fast Whitelisted Proxy Test Service
========================================

High-performance IP whitelisting + full proxy detection capabilities
- Redis caching for microsecond lookups
- Complete proxy anonymity/speed analysis
- Rate limiting per customer plan
- Usage tracking for billing
"""

from flask import Flask, request, jsonify, render_template_string, Response
from functools import wraps
import redis
import sqlite3
import ipaddress
import time
from datetime import datetime, timedelta
import json
from typing import Optional, Dict, Any
import orjson

app = Flask(__name__)
print("Available routes:", [rule.rule for rule in app.url_map.iter_rules()])

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
DB_PATH = 'whitelist.db'

# Initialize Redis connection
try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    print("⚠️ Redis not available - using database only")

class IPWhitelistManager:
    def __init__(self):
        self.init_database()
        self.cache_timeout = 300
        
    def init_database(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ip_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT UNIQUE NOT NULL,
                customer_id TEXT NOT NULL,
                plan_type TEXT DEFAULT 'basic',
                rate_limit INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                notes TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                response_time_ms REAL,
                success BOOLEAN DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip_address TEXT PRIMARY KEY,
                requests_count INTEGER DEFAULT 0,
                window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def add_ip(self, ip_address: str, customer_id: str, plan_type: str = 'basic', 
               rate_limit: int = 100, expires_days: int = 30, notes: str = '') -> bool:
        try:
            ipaddress.ip_address(ip_address)
            expires_at = datetime.now() + timedelta(days=expires_days)
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO ip_whitelist 
                (ip_address, customer_id, plan_type, rate_limit, expires_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (ip_address, customer_id, plan_type, rate_limit, expires_at, notes))
            
            conn.commit()
            conn.close()
            
            if REDIS_AVAILABLE:
                cache_key = f"whitelist:{ip_address}"
                cache_data = {
                    'customer_id': customer_id,
                    'plan_type': plan_type,
                    'rate_limit': rate_limit,
                    'expires_at': expires_at.isoformat()
                }
                redis_client.setex(cache_key, self.cache_timeout, json.dumps(cache_data))
                
            return True
            
        except Exception as e:
            print(f"Error adding IP {ip_address}: {e}")
            return False
    
    def remove_ip(self, ip_address: str) -> bool:
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE ip_whitelist SET is_active = 0 WHERE ip_address = ?', (ip_address,))
            conn.commit()
            conn.close()
            
            if REDIS_AVAILABLE:
                redis_client.delete(f"whitelist:{ip_address}")
                
            return True
        except Exception as e:
            print(f"Error removing IP {ip_address}: {e}")
            return False
    
    def is_ip_allowed(self, ip_address: str) -> tuple[bool, Optional[Dict[str, Any]]]:
        # Redis cache check first
        if REDIS_AVAILABLE:
            cache_key = f"whitelist:{ip_address}"
            cached_data = redis_client.get(cache_key)
            if cached_data:
                try:
                    data = json.loads(cached_data)
                    if datetime.fromisoformat(data['expires_at']) > datetime.now():
                        return True, data
                except:
                    pass
        
        # Database fallback
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT customer_id, plan_type, rate_limit, expires_at 
                FROM ip_whitelist 
                WHERE ip_address = ? AND is_active = 1
            ''', (ip_address,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                customer_id, plan_type, rate_limit, expires_at = result
                expires_dt = datetime.fromisoformat(expires_at)
                
                if expires_dt > datetime.now():
                    data = {
                        'customer_id': customer_id,
                        'plan_type': plan_type,
                        'rate_limit': rate_limit,
                        'expires_at': expires_at
                    }
                    
                    if REDIS_AVAILABLE:
                        cache_key = f"whitelist:{ip_address}"
                        redis_client.setex(cache_key, self.cache_timeout, json.dumps(data))
                    
                    return True, data
                    
            return False, None
            
        except Exception as e:
            print(f"Error checking IP {ip_address}: {e}")
            return False, None
    
    def check_rate_limit(self, ip_address: str, rate_limit: int) -> bool:
        window_duration = 60
        
        if REDIS_AVAILABLE:
            key = f"rate_limit:{ip_address}"
            current_count = redis_client.incr(key)
            if current_count == 1:
                redis_client.expire(key, window_duration)
            return current_count <= rate_limit
        else:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT requests_count, window_start FROM rate_limits WHERE ip_address = ?
            ''', (ip_address,))
            
            result = cursor.fetchone()
            
            if result:
                count, window_start = result
                window_start_dt = datetime.fromisoformat(window_start)
                
                if datetime.now() - window_start_dt > timedelta(seconds=window_duration):
                    cursor.execute('''
                        UPDATE rate_limits SET requests_count = 1, window_start = CURRENT_TIMESTAMP
                        WHERE ip_address = ?
                    ''', (ip_address,))
                    count = 1
                else:
                    cursor.execute('''
                        UPDATE rate_limits SET requests_count = requests_count + 1
                        WHERE ip_address = ?
                    ''', (ip_address,))
                    count += 1
            else:
                cursor.execute('''
                    INSERT INTO rate_limits (ip_address, requests_count)
                    VALUES (?, 1)
                ''', (ip_address,))
                count = 1
            
            conn.commit()
            conn.close()
            return count <= rate_limit
    
    def log_usage(self, ip_address: str, customer_id: str, endpoint: str, 
                  response_time_ms: float, success: bool = True):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO usage_logs (ip_address, customer_id, endpoint, response_time_ms, success)
                VALUES (?, ?, ?, ?, ?)
            ''', (ip_address, customer_id, endpoint, response_time_ms, success))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging usage: {e}")

# Initialize whitelist manager
whitelist_manager = IPWhitelistManager()

# Proxy detection functions
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

def require_whitelisted_ip(f):
    """Decorator for IP whitelisting with minimal overhead"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        
        if ',' in client_ip:
            client_ip = client_ip.split(',')[0].strip()
        
        is_allowed, client_data = whitelist_manager.is_ip_allowed(client_ip)
        
        if not is_allowed:
            whitelist_manager.log_usage(client_ip, 'unknown', request.endpoint, 
                                      (time.time() - start_time) * 1000, False)
            return Response(orjson.dumps({
                'error': 'Access denied',
                'message': 'IP not whitelisted for paid service',
                'ip': client_ip,
                'contact': 'sales@yourservice.com'
            }), status=403, mimetype='application/json')
        
        if not whitelist_manager.check_rate_limit(client_ip, client_data['rate_limit']):
            whitelist_manager.log_usage(client_ip, client_data['customer_id'], 
                                      request.endpoint, (time.time() - start_time) * 1000, False)
            return Response(orjson.dumps({
                'error': 'Rate limit exceeded',
                'message': f"Rate limit: {client_data['rate_limit']} requests/minute",
                'plan': client_data['plan_type']
            }), status=429, mimetype='application/json')
        
        result = f(*args, **kwargs)
        
        response_time = (time.time() - start_time) * 1000
        whitelist_manager.log_usage(client_ip, client_data['customer_id'], 
                                  request.endpoint, response_time, True)
        
        return result
    
    return decorated_function

# Main proxy test endpoint - ultra-fast with full detection
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
@require_whitelisted_ip
def proxy_test_endpoint(path):
    """Ultra-fast proxy testing endpoint with complete analysis"""
    start_time = time.time()

    connecting_ip = request.remote_addr
    client_ip_from_headers = get_client_ip(request)
    server_processing_latency_ms = (time.time() - start_time) * 1000
    anonymity_level = determine_anonymity(request, connecting_ip)
    
    response_data = {
        "status": "success",
        "message": "Premium proxy test endpoint active",
        "received_path": f"/{path}",
        "method": request.method,
        "headers_received": dict(request.headers),
        "connecting_ip": connecting_ip,
        "client_ip_from_headers": client_ip_from_headers,
        "anonymity_level": anonymity_level,
        "server_processing_latency_ms": server_processing_latency_ms,
        "speed_hint": determine_speed(server_processing_latency_ms),
        "args": dict(request.args),
        "form": dict(request.form),
        "json_body": request.json if request.is_json else None
    }
    
    return Response(orjson.dumps(response_data), mimetype='application/json')

# Dedicated ping endpoints for different use cases
@app.route("/ping", methods=["GET"])
@require_whitelisted_ip
def ping():
    """Ultra-fast ping endpoint"""
    payload = {
        "anonymity_level": determine_anonymity(request, request.remote_addr),
        "client_ip_from_headers": get_client_ip(request),
        "message": "Premium proxy test endpoint active",
        "status": "success"
    }
    return Response(orjson.dumps(payload), mimetype='application/json')

@app.route('/health')
@require_whitelisted_ip  
def health():
    return Response(orjson.dumps({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'premium-proxy-test'
    }), mimetype='application/json')

@app.route('/fast-ping')
@require_whitelisted_ip
def fast_ping():
    return Response(orjson.dumps({'pong': time.time()}), mimetype='application/json')

# Admin interface
@app.route('/admin/whitelist')
def admin_whitelist():
    admin_html = '''
    <!DOCTYPE html>
    <html>
    <head><title>IP Whitelist Admin</title></head>
    <body>
        <h1>🔐 IP Whitelist Management</h1>
        
        <h2>Add New IP</h2>
        <form action="/admin/add_ip" method="post">
            <input type="text" name="ip_address" placeholder="IP Address" required><br><br>
            <input type="text" name="customer_id" placeholder="Customer ID" required><br><br>
            <select name="plan_type">
                <option value="basic">Basic (100/min)</option>
                <option value="premium">Premium (500/min)</option>
                <option value="enterprise">Enterprise (2000/min)</option>
            </select><br><br>
            <input type="number" name="expires_days" value="30" placeholder="Expires in days"><br><br>
            <input type="text" name="notes" placeholder="Notes (optional)"><br><br>
            <button type="submit">Add IP</button>
        </form>
        
        <h2>Remove IP</h2>
        <form action="/admin/remove_ip" method="post">
            <input type="text" name="ip_address" placeholder="IP Address" required><br><br>
            <button type="submit">Remove IP</button>
        </form>
    </body>
    </html>
    '''
    return render_template_string(admin_html)

@app.route('/admin/add_ip', methods=['POST'])
def admin_add_ip():
    ip_address = request.form.get('ip_address')
    customer_id = request.form.get('customer_id')
    plan_type = request.form.get('plan_type', 'basic')
    expires_days = int(request.form.get('expires_days', 30))
    notes = request.form.get('notes', '')
    
    rate_limits = {'basic': 100, 'premium': 500, 'enterprise': 2000}
    rate_limit = rate_limits.get(plan_type, 100)
    
    success = whitelist_manager.add_ip(ip_address, customer_id, plan_type, 
                                     rate_limit, expires_days, notes)
    
    if success:
        return jsonify({'success': True, 'message': f'IP {ip_address} added successfully'})
    else:
        return jsonify({'success': False, 'message': 'Failed to add IP'}), 400

@app.route('/admin/remove_ip', methods=['POST'])
def admin_remove_ip():
    ip_address = request.form.get('ip_address')
    success = whitelist_manager.remove_ip(ip_address)
    
    if success:
        return jsonify({'success': True, 'message': f'IP {ip_address} removed successfully'})
    else:
        return jsonify({'success': False, 'message': 'Failed to remove IP'}), 400

# Public status endpoint (no whitelist)
@app.route('/status')
def status():
    return Response(orjson.dumps({
        'service': 'premium-proxy-test-api',
        'status': 'operational',
        'message': 'Contact sales@yourservice.com for access'
    }), mimetype='application/json')

if __name__ == '__main__':
    print("🚀 Initializing Premium Proxy Test Service...")
    
    # Add development IPs
    whitelist_manager.add_ip('127.0.0.1', 'dev-001', 'enterprise', 2000, 365, 'Development IP')
    whitelist_manager.add_ip('localhost', 'dev-002', 'enterprise', 2000, 365, 'Localhost testing')
    
    print("✅ System ready!")
    print("📝 Admin interface: http://localhost:9876/admin/whitelist")
    print("🔒 Protected endpoints: /, /ping, /health, /fast-ping")
    
    app.run(host='0.0.0.0', port=9876, debug=True)