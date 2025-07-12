"""
Customer Resource Manager Extension
===================================

Automated IP/Port assignment, usage monitoring, and billing preparation
- Automatic resource pool management
- Customer lifecycle automation
- Billing data aggregation
- Resource allocation algorithms
"""

import sqlite3
import ipaddress
import random
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import json
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

class CustomerStatus(Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    PENDING = "pending"

class ResourceType(Enum):
    IP_ONLY = "ip_only"
    IP_PORT = "ip_port"
    PORT_RANGE = "port_range"

@dataclass
class CustomerResource:
    customer_id: str
    ip_address: str
    port_start: Optional[int] = None
    port_end: Optional[int] = None
    resource_type: ResourceType = ResourceType.IP_ONLY
    allocated_at: datetime = None
    expires_at: datetime = None

@dataclass
class BillingPeriod:
    customer_id: str
    period_start: datetime
    period_end: datetime
    total_requests: int
    total_bandwidth_mb: float
    overage_requests: int
    base_cost: float
    overage_cost: float
    total_cost: float

class CustomerResourceManager:
    def __init__(self, db_path: str = 'customer_resources.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.init_database()
        self.init_resource_pools()
        
    def init_database(self):
        """Initialize extended database schema for customer management"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Customers table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                company_name TEXT,
                plan_type TEXT DEFAULT 'basic',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                billing_email TEXT,
                api_key TEXT UNIQUE,
                monthly_quota INTEGER DEFAULT 10000,
                current_usage INTEGER DEFAULT 0,
                billing_cycle_start INTEGER DEFAULT 1,
                notes TEXT
            )
        ''')
        
        # Resource allocations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resource_allocations (
                allocation_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                port_start INTEGER,
                port_end INTEGER,
                resource_type TEXT NOT NULL,
                allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                last_used TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # Resource pools table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resource_pools (
                pool_id TEXT PRIMARY KEY,
                ip_address TEXT NOT NULL,
                port_start INTEGER,
                port_end INTEGER,
                resource_type TEXT NOT NULL,
                is_available BOOLEAN DEFAULT 1,
                reserved_for_plan TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Billing periods table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS billing_periods (
                period_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                period_start TIMESTAMP NOT NULL,
                period_end TIMESTAMP NOT NULL,
                total_requests INTEGER DEFAULT 0,
                total_bandwidth_mb REAL DEFAULT 0,
                base_cost REAL DEFAULT 0,
                overage_cost REAL DEFAULT 0,
                total_cost REAL DEFAULT 0,
                invoice_generated BOOLEAN DEFAULT 0,
                paid BOOLEAN DEFAULT 0,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # Usage aggregation table for billing
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usage_aggregates (
                customer_id TEXT,
                date DATE,
                total_requests INTEGER DEFAULT 0,
                total_bandwidth_mb REAL DEFAULT 0,
                peak_concurrent INTEGER DEFAULT 0,
                avg_response_time_ms REAL DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                PRIMARY KEY (customer_id, date),
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def init_resource_pools(self):
        """Initialize available IP/port pools"""
        # Define your available IP ranges and port ranges
        base_ips = [
            "10.0.1.0/24",    # Private range for testing
            "192.168.100.0/24"  # Another private range
        ]
        
        port_ranges = [
            (8000, 8999),     # Port range 1
            (9000, 9999),     # Port range 2
            (10000, 10999)    # Port range 3
        ]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Add IP-only resources
        for ip_range in base_ips:
            network = ipaddress.IPv4Network(ip_range, strict=False)
            for ip in network.hosts():
                pool_id = str(uuid.uuid4())
                cursor.execute('''
                    INSERT OR IGNORE INTO resource_pools 
                    (pool_id, ip_address, resource_type, reserved_for_plan)
                    VALUES (?, ?, ?, ?)
                ''', (pool_id, str(ip), ResourceType.IP_ONLY.value, 'basic'))
        
        # Add IP+Port combinations for premium plans
        for ip_range in base_ips[:1]:  # Use fewer IPs for premium
            network = ipaddress.IPv4Network(ip_range, strict=False)
            for i, ip in enumerate(list(network.hosts())[:10]):  # Limit to 10 IPs
                for port_start, port_end in port_ranges:
                    pool_id = str(uuid.uuid4())
                    cursor.execute('''
                        INSERT OR IGNORE INTO resource_pools 
                        (pool_id, ip_address, port_start, port_end, resource_type, reserved_for_plan)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (pool_id, str(ip), port_start, port_end, 
                         ResourceType.IP_PORT.value, 'premium'))
        
        conn.commit()
        conn.close()
    
    def create_customer(self, email: str, company_name: str = None, 
                       plan_type: str = 'basic') -> Tuple[bool, str]:
        """Create new customer with automatic resource allocation"""
        with self.lock:
            try:
                customer_id = f"cust_{uuid.uuid4().hex[:12]}"
                api_key = f"ak_{uuid.uuid4().hex}"
                
                # Determine quotas based on plan
                quotas = {
                    'basic': 10000,
                    'premium': 50000, 
                    'enterprise': 200000
                }
                monthly_quota = quotas.get(plan_type, 10000)
                
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Create customer record
                cursor.execute('''
                    INSERT INTO customers 
                    (customer_id, email, company_name, plan_type, api_key, monthly_quota)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (customer_id, email, company_name, plan_type, api_key, monthly_quota))
                
                # Allocate resources
                resource = self._allocate_resource(customer_id, plan_type, cursor)
                
                if not resource:
                    conn.rollback()
                    conn.close()
                    return False, "No available resources for plan type"
                
                # Add to original whitelist system
                from proxy-test-app import whitelist_manager
                rate_limits = {'basic': 100, 'premium': 500, 'enterprise': 2000}
                success = whitelist_manager.add_ip(
                    resource.ip_address, 
                    customer_id, 
                    plan_type,
                    rate_limits.get(plan_type, 100),
                    30,
                    f"Auto-allocated for {email}"
                )
                
                if not success:
                    conn.rollback()
                    conn.close()
                    return False, "Failed to add to whitelist"
                
                conn.commit()
                conn.close()
                
                return True, customer_id
                
            except Exception as e:
                print(f"Error creating customer: {e}")
                return False, str(e)
    
    def _allocate_resource(self, customer_id: str, plan_type: str, 
                          cursor) -> Optional[CustomerResource]:
        """Allocate appropriate resource based on plan type"""
        
        # Determine resource type based on plan
        if plan_type == 'basic':
            resource_type = ResourceType.IP_ONLY
        elif plan_type == 'premium':
            resource_type = ResourceType.IP_PORT
        else:  # enterprise
            resource_type = ResourceType.PORT_RANGE
        
        # Find available resource
        cursor.execute('''
            SELECT pool_id, ip_address, port_start, port_end 
            FROM resource_pools 
            WHERE resource_type = ? AND is_available = 1 
            AND (reserved_for_plan = ? OR reserved_for_plan IS NULL)
            ORDER BY RANDOM() 
            LIMIT 1
        ''', (resource_type.value, plan_type))
        
        result = cursor.fetchone()
        if not result:
            return None
        
        pool_id, ip_address, port_start, port_end = result
        
        # Mark resource as allocated
        cursor.execute('''
            UPDATE resource_pools SET is_available = 0 WHERE pool_id = ?
        ''', (pool_id,))
        
        # Create allocation record
        allocation_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=30)
        
        cursor.execute('''
            INSERT INTO resource_allocations 
            (allocation_id, customer_id, ip_address, port_start, port_end, 
             resource_type, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (allocation_id, customer_id, ip_address, port_start, port_end,
             resource_type.value, expires_at))
        
        return CustomerResource(
            customer_id=customer_id,
            ip_address=ip_address,
            port_start=port_start,
            port_end=port_end,
            resource_type=resource_type,
            allocated_at=datetime.now(),
            expires_at=expires_at
        )
    
    def get_customer_resources(self, customer_id: str) -> List[CustomerResource]:
        """Get all resources allocated to a customer"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ip_address, port_start, port_end, resource_type, 
                   allocated_at, expires_at
            FROM resource_allocations 
            WHERE customer_id = ? AND is_active = 1
        ''', (customer_id,))
        
        resources = []
        for row in cursor.fetchall():
            ip, port_start, port_end, res_type, allocated, expires = row
            resources.append(CustomerResource(
                customer_id=customer_id,
                ip_address=ip,
                port_start=port_start,
                port_end=port_end,
                resource_type=ResourceType(res_type),
                allocated_at=datetime.fromisoformat(allocated) if allocated else None,
                expires_at=datetime.fromisoformat(expires) if expires else None
            ))
        
        conn.close()
        return resources
    
    def aggregate_usage_for_billing(self, customer_id: str, 
                                  period_start: datetime, 
                                  period_end: datetime) -> BillingPeriod:
        """Aggregate usage data for billing period"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get customer plan details
        cursor.execute('''
            SELECT plan_type, monthly_quota FROM customers WHERE customer_id = ?
        ''', (customer_id,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return None
        
        plan_type, monthly_quota = result
        
        # Aggregate usage from original usage_logs table
        cursor.execute('''
            SELECT COUNT(*) as total_requests,
                   AVG(response_time_ms) as avg_response_time,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count
            FROM usage_logs 
            WHERE customer_id = ? 
            AND timestamp BETWEEN ? AND ?
        ''', (customer_id, period_start.isoformat(), period_end.isoformat()))
        
        usage_result = cursor.fetchone()
        total_requests, avg_response_time, error_count = usage_result or (0, 0, 0)
        
        # Calculate costs
        base_costs = {'basic': 29.99, 'premium': 99.99, 'enterprise': 299.99}
        overage_rates = {'basic': 0.01, 'premium': 0.008, 'enterprise': 0.005}
        
        base_cost = base_costs.get(plan_type, 29.99)
        overage_requests = max(0, total_requests - monthly_quota)
        overage_cost = overage_requests * overage_rates.get(plan_type, 0.01)
        total_cost = base_cost + overage_cost
        
        # Estimate bandwidth (rough calculation)
        estimated_bandwidth_mb = total_requests * 0.05  # 50KB average per request
        
        billing_period = BillingPeriod(
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
            total_requests=total_requests or 0,
            total_bandwidth_mb=estimated_bandwidth_mb,
            overage_requests=overage_requests,
            base_cost=base_cost,
            overage_cost=overage_cost,
            total_cost=total_cost
        )
        
        # Store billing period
        period_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT OR REPLACE INTO billing_periods 
            (period_id, customer_id, period_start, period_end, total_requests,
             total_bandwidth_mb, base_cost, overage_cost, total_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (period_id, customer_id, period_start.isoformat(), 
             period_end.isoformat(), total_requests, estimated_bandwidth_mb,
             base_cost, overage_cost, total_cost))
        
        conn.commit()
        conn.close()
        
        return billing_period
    
    def cleanup_expired_resources(self):
        """Clean up expired resource allocations"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Find expired allocations
            cursor.execute('''
                SELECT allocation_id, ip_address FROM resource_allocations 
                WHERE expires_at < ? AND is_active = 1
            ''', (datetime.now().isoformat(),))
            
            expired = cursor.fetchall()
            
            for allocation_id, ip_address in expired:
                # Deactivate allocation
                cursor.execute('''
                    UPDATE resource_allocations SET is_active = 0 
                    WHERE allocation_id = ?
                ''', (allocation_id,))
                
                # Return resource to pool
                cursor.execute('''
                    UPDATE resource_pools SET is_available = 1 
                    WHERE ip_address = ?
                ''', (ip_address,))
                
                # Remove from whitelist
                from proxy-test-app import whitelist_manager
                whitelist_manager.remove_ip(ip_address)
            
            conn.commit()
            conn.close()
            
            print(f"Cleaned up {len(expired)} expired resource allocations")
    
    def get_billing_summary(self, customer_id: str, 
                           months_back: int = 3) -> List[BillingPeriod]:
        """Get billing summary for customer"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        since_date = datetime.now() - timedelta(days=months_back * 30)
        
        cursor.execute('''
            SELECT customer_id, period_start, period_end, total_requests,
                   total_bandwidth_mb, base_cost, overage_cost, total_cost
            FROM billing_periods 
            WHERE customer_id = ? AND period_start >= ?
            ORDER BY period_start DESC
        ''', (customer_id, since_date.isoformat()))
        
        billing_periods = []
        for row in cursor.fetchall():
            cust_id, start, end, requests, bandwidth, base, overage, total = row
            
            billing_periods.append(BillingPeriod(
                customer_id=cust_id,
                period_start=datetime.fromisoformat(start),
                period_end=datetime.fromisoformat(end),
                total_requests=requests,
                total_bandwidth_mb=bandwidth,
                overage_requests=max(0, requests - 10000),  # Simplified
                base_cost=base,
                overage_cost=overage,
                total_cost=total
            ))
        
        conn.close()
        return billing_periods

# Integration functions for your existing Flask app
def integrate_with_existing_app(app, whitelist_manager):
    """Add new endpoints to existing Flask app"""
    
    customer_manager = CustomerResourceManager()
    
    @app.route('/api/customers', methods=['POST'])
    def create_customer_api():
        data = request.get_json()
        email = data.get('email')
        company = data.get('company_name')
        plan = data.get('plan_type', 'basic')
        
        success, result = customer_manager.create_customer(email, company, plan)
        
        if success:
            resources = customer_manager.get_customer_resources(result)
            return jsonify({
                'success': True,
                'customer_id': result,
                'allocated_resources': [asdict(r) for r in resources]
            })
        else:
            return jsonify({'success': False, 'error': result}), 400
    
    @app.route('/api/customers/<customer_id>/billing')
    def get_customer_billing(customer_id):
        periods = customer_manager.get_billing_summary(customer_id)
        return jsonify({
            'customer_id': customer_id,
            'billing_periods': [asdict(p) for p in periods]
        })
    
    @app.route('/api/customers/<customer_id>/resources')
    def get_customer_resources_api(customer_id):
        resources = customer_manager.get_customer_resources(customer_id)
        return jsonify({
            'customer_id': customer_id,
            'resources': [asdict(r) for r in resources]
        })
    
    # Background cleanup task
    import threading
    import time
    
    def cleanup_worker():
        while True:
            try:
                customer_manager.cleanup_expired_resources()
                time.sleep(3600)  # Run every hour
            except Exception as e:
                print(f"Cleanup error: {e}")
                time.sleep(3600)
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    