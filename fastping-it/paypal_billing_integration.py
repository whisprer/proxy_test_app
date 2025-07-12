"""
PayPal Billing & Invoice Integration
===================================

Complete PayPal integration for subscription billing and automated invoicing
- Subscription plans management
- Automated recurring billing
- Usage-based overage invoicing
- Webhook handling for payment events
- Customer billing portal integration
"""

import requests
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sqlite3
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
import hmac
import hashlib
from decimal import Decimal

class PayPalEnvironment(Enum):
    SANDBOX = "https://api-m.sandbox.paypal.com"
    LIVE = "https://api-m.paypal.com"

class SubscriptionStatus(Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"

@dataclass
class PayPalPlan:
    plan_id: str
    name: str
    description: str
    monthly_price: Decimal
    request_limit: int
    overage_rate: Decimal
    features: List[str]

@dataclass
class CustomerSubscription:
    subscription_id: str
    customer_id: str
    plan_id: str
    status: SubscriptionStatus
    next_billing_date: datetime
    created_at: datetime
    paypal_subscriber_id: str

class PayPalBillingManager:
    def __init__(self, client_id: str, client_secret: str, 
                 environment: PayPalEnvironment = PayPalEnvironment.SANDBOX,
                 webhook_id: str = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = environment.value
        self.webhook_id = webhook_id
        self.access_token = None
        self.token_expires_at = None
        
        self.init_database()
        self.setup_billing_plans()
    
    def init_database(self):
        """Initialize PayPal billing database tables"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        # PayPal subscriptions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paypal_subscriptions (
                subscription_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                paypal_subscription_id TEXT UNIQUE NOT NULL,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                next_billing_date TIMESTAMP,
                last_payment_date TIMESTAMP,
                failed_payment_count INTEGER DEFAULT 0,
                paypal_subscriber_id TEXT,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # PayPal plans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS paypal_plans (
                plan_id TEXT PRIMARY KEY,
                paypal_plan_id TEXT UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                monthly_price DECIMAL(10,2),
                request_limit INTEGER,
                overage_rate DECIMAL(6,4),
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Overage invoices table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS overage_invoices (
                invoice_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                paypal_invoice_id TEXT UNIQUE,
                billing_period_start TIMESTAMP NOT NULL,
                billing_period_end TIMESTAMP NOT NULL,
                overage_requests INTEGER NOT NULL,
                overage_amount DECIMAL(10,2) NOT NULL,
                status TEXT DEFAULT 'DRAFT',
                sent_at TIMESTAMP,
                paid_at TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        # Payment events log
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_events (
                event_id TEXT PRIMARY KEY,
                paypal_event_id TEXT UNIQUE,
                event_type TEXT NOT NULL,
                customer_id TEXT,
                subscription_id TEXT,
                invoice_id TEXT,
                amount DECIMAL(10,2),
                currency TEXT DEFAULT 'USD',
                status TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                webhook_data TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_access_token(self) -> str:
        """Get or refresh PayPal access token"""
        if (self.access_token and self.token_expires_at and 
            datetime.now() < self.token_expires_at):
            return self.access_token
        
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            'Accept': 'application/json',
            'Accept-Language': 'en_US',
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = 'grant_type=client_credentials'
        
        response = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            headers=headers,
            data=data
        )
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            return self.access_token
        else:
            raise Exception(f"Failed to get access token: {response.text}")
    
    def setup_billing_plans(self):
        """Create PayPal billing plans for your service tiers"""
        plans_config = [
            {
                'name': 'Basic Proxy Plan',
                'description': 'Basic proxy testing with 10,000 requests/month',
                'monthly_price': Decimal('29.99'),
                'request_limit': 10000,
                'overage_rate': Decimal('0.01'),
                'features': ['IP whitelisting', 'Basic support', '100 req/min rate limit']
            },
            {
                'name': 'Premium Proxy Plan', 
                'description': 'Premium proxy testing with 50,000 requests/month',
                'monthly_price': Decimal('99.99'),
                'request_limit': 50000,
                'overage_rate': Decimal('0.008'),
                'features': ['IP + Port allocation', 'Priority support', '500 req/min rate limit']
            },
            {
                'name': 'Enterprise Proxy Plan',
                'description': 'Enterprise proxy testing with 200,000 requests/month', 
                'monthly_price': Decimal('299.99'),
                'request_limit': 200000,
                'overage_rate': Decimal('0.005'),
                'features': ['Port ranges', '24/7 support', '2000 req/min rate limit', 'Custom integrations']
            }
        ]
        
        for plan_config in plans_config:
            self.create_paypal_plan(plan_config)
    
    def create_paypal_plan(self, plan_config: Dict) -> str:
        """Create a billing plan in PayPal"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}',
            'PayPal-Request-Id': str(uuid.uuid4())
        }
        
        plan_data = {
            "product_id": self.create_product(plan_config['name'], plan_config['description']),
            "name": plan_config['name'],
            "description": plan_config['description'],
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {
                        "interval_unit": "MONTH",
                        "interval_count": 1
                    },
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,  # Infinite
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(plan_config['monthly_price']),
                            "currency_code": "USD"
                        }
                    }
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3
            }
        }
        
        response = requests.post(
            f"{self.base_url}/v1/billing/plans",
            headers=headers,
            json=plan_data
        )
        
        if response.status_code == 201:
            paypal_plan = response.json()
            plan_id = f"plan_{uuid.uuid4().hex[:8]}"
            
            # Store in database
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO paypal_plans 
                (plan_id, paypal_plan_id, name, description, monthly_price, 
                 request_limit, overage_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (plan_id, paypal_plan['id'], plan_config['name'],
                 plan_config['description'], plan_config['monthly_price'],
                 plan_config['request_limit'], plan_config['overage_rate']))
            conn.commit()
            conn.close()
            
            return plan_id
        else:
            print(f"Failed to create plan: {response.text}")
            return None
    
    def create_product(self, name: str, description: str) -> str:
        """Create a PayPal product (required for billing plans)"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}',
            'PayPal-Request-Id': str(uuid.uuid4())
        }
        
        product_data = {
            "name": name,
            "description": description,
            "type": "SERVICE",
            "category": "SOFTWARE"
        }
        
        response = requests.post(
            f"{self.base_url}/v1/catalogs/products",
            headers=headers,
            json=product_data
        )
        
        if response.status_code == 201:
            return response.json()['id']
        else:
            raise Exception(f"Failed to create product: {response.text}")
    
    def create_subscription(self, customer_id: str, plan_id: str, 
                          customer_email: str, customer_name: str) -> Tuple[bool, str]:
        """Create a PayPal subscription for a customer"""
        
        # Get plan details
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT paypal_plan_id, name FROM paypal_plans WHERE plan_id = ?
        ''', (plan_id,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return False, "Plan not found"
        
        paypal_plan_id, plan_name = result
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}',
            'PayPal-Request-Id': str(uuid.uuid4())
        }
        
        subscription_data = {
            "plan_id": paypal_plan_id,
            "start_time": (datetime.now() + timedelta(minutes=5)).isoformat() + "Z",
            "subscriber": {
                "name": {
                    "given_name": customer_name.split()[0] if customer_name else "Customer",
                    "surname": customer_name.split()[-1] if ' ' in customer_name else "User"
                },
                "email_address": customer_email
            },
            "application_context": {
                "brand_name": "Your Proxy Service",
                "locale": "en-US",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
                },
                "return_url": "https://yourservice.com/subscription/success",
                "cancel_url": "https://yourservice.com/subscription/cancel"
            }
        }
        
        response = requests.post(
            f"{self.base_url}/v1/billing/subscriptions",
            headers=headers,
            json=subscription_data
        )
        
        if response.status_code == 201:
            subscription = response.json()
            subscription_id = str(uuid.uuid4())
            
            # Store subscription
            cursor.execute('''
                INSERT INTO paypal_subscriptions 
                (subscription_id, customer_id, paypal_subscription_id, plan_id, 
                 status, next_billing_date, paypal_subscriber_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (subscription_id, customer_id, subscription['id'], plan_id,
                 'ACTIVE', datetime.now() + timedelta(days=30), 
                 subscription.get('subscriber', {}).get('payer_id')))
            
            conn.commit()
            conn.close()
            
            # Return approval URL for customer to complete setup
            approval_url = next(
                (link['href'] for link in subscription.get('links', []) 
                 if link['rel'] == 'approve'), 
                None
            )
            
            return True, approval_url
        else:
            conn.close()
            return False, f"Failed to create subscription: {response.text}"
    
    def create_overage_invoice(self, customer_id: str, overage_requests: int,
                             period_start: datetime, period_end: datetime) -> Tuple[bool, str]:
        """Create an invoice for overage usage"""
        
        # Get customer and plan details
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.email, c.company_name, ps.plan_id
            FROM customers c
            JOIN paypal_subscriptions ps ON c.customer_id = ps.customer_id
            WHERE c.customer_id = ? AND ps.status = 'ACTIVE'
        ''', (customer_id,))
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return False, "Customer or active subscription not found"
        
        email, company_name, plan_id = result
        
        # Get overage rate
        cursor.execute('''
            SELECT overage_rate FROM paypal_plans WHERE plan_id = ?
        ''', (plan_id,))
        
        overage_rate = cursor.fetchone()[0]
        overage_amount = Decimal(str(overage_requests)) * Decimal(str(overage_rate))
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}',
            'PayPal-Request-Id': str(uuid.uuid4())
        }
        
        invoice_data = {
            "detail": {
                "invoice_number": f"OVR-{customer_id[:8]}-{int(datetime.now().timestamp())}",
                "reference": f"Overage for {period_start.strftime('%B %Y')}",
                "invoice_date": datetime.now().strftime('%Y-%m-%d'),
                "currency_code": "USD",
                "note": f"Overage charges for {overage_requests:,} requests above your plan limit",
                "term": "Due upon receipt",
                "memo": "Proxy service overage billing"
            },
            "invoicer": {
                "name": {"business_name": "Your Proxy Service"},
                "address": {
                    "address_line_1": "123 Service Street",
                    "admin_area_2": "San Francisco",
                    "admin_area_1": "CA",
                    "postal_code": "94102",
                    "country_code": "US"
                },
                "email_address": "billing@yourservice.com"
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "name": {"business_name": company_name or "Customer"},
                        "email_address": email
                    }
                }
            ],
            "items": [
                {
                    "name": "API Request Overage",
                    "description": f"Additional requests beyond plan limit for {period_start.strftime('%B %Y')}",
                    "quantity": str(overage_requests),
                    "unit_amount": {
                        "currency_code": "USD",
                        "value": str(overage_rate)
                    },
                    "unit_of_measure": "QUANTITY"
                }
            ],
            "configuration": {
                "partial_payment": {
                    "allow_partial_payment": False
                },
                "allow_tip": False,
                "tax_calculated_after_discount": True,
                "tax_inclusive": False
            }
        }
        
        response = requests.post(
            f"{self.base_url}/v2/invoicing/invoices",
            headers=headers,
            json=invoice_data
        )
        
        if response.status_code == 201:
            invoice = response.json()
            invoice_id = str(uuid.uuid4())
            
            # Store invoice
            cursor.execute('''
                INSERT INTO overage_invoices 
                (invoice_id, customer_id, paypal_invoice_id, billing_period_start,
                 billing_period_end, overage_requests, overage_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (invoice_id, customer_id, invoice['id'], period_start.isoformat(),
                 period_end.isoformat(), overage_requests, overage_amount, 'DRAFT'))
            
            conn.commit()
            conn.close()
            
            # Send the invoice
            self.send_invoice(invoice['id'])
            
            return True, invoice['id']
        else:
            conn.close()
            return False, f"Failed to create invoice: {response.text}"
    
    def send_invoice(self, paypal_invoice_id: str) -> bool:
        """Send an invoice to the customer"""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.get_access_token()}'
        }
        
        send_data = {
            "send_to_recipient": True,
            "send_to_invoicer": True
        }
        
        response = requests.post(
            f"{self.base_url}/v2/invoicing/invoices/{paypal_invoice_id}/send",
            headers=headers,
            json=send_data
        )
        
        if response.status_code == 202:
            # Update invoice status
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE overage_invoices 
                SET status = 'SENT', sent_at = CURRENT_TIMESTAMP
                WHERE paypal_invoice_id = ?
            ''', (paypal_invoice_id,))
            conn.commit()
            conn.close()
            return True
        else:
            print(f"Failed to send invoice: {response.text}")
            return False
    
    def handle_webhook(self, webhook_data: Dict, headers: Dict) -> bool:
        """Handle PayPal webhook events"""
        
        # Verify webhook signature (production security)
        if self.webhook_id and not self.verify_webhook_signature(webhook_data, headers):
            return False
        
        event_type = webhook_data.get('event_type')
        resource = webhook_data.get('resource', {})
        
        # Store event
        event_id = str(uuid.uuid4())
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO payment_events 
            (event_id, paypal_event_id, event_type, webhook_data)
            VALUES (?, ?, ?, ?)
        ''', (event_id, webhook_data.get('id'), event_type, json.dumps(webhook_data)))
        
        # Process different event types
        if event_type == 'BILLING.SUBSCRIPTION.ACTIVATED':
            self.handle_subscription_activated(resource, cursor)
        elif event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
            self.handle_subscription_cancelled(resource, cursor)
        elif event_type == 'PAYMENT.SALE.COMPLETED':
            self.handle_payment_completed(resource, cursor)
        elif event_type == 'INVOICING.INVOICE.PAID':
            self.handle_invoice_paid(resource, cursor)
        elif event_type == 'BILLING.SUBSCRIPTION.PAYMENT.FAILED':
            self.handle_payment_failed(resource, cursor)
        
        conn.commit()
        conn.close()
        return True
    
    def handle_subscription_activated(self, resource: Dict, cursor):
        """Handle subscription activation"""
        paypal_sub_id = resource.get('id')
        if paypal_sub_id:
            cursor.execute('''
                UPDATE paypal_subscriptions 
                SET status = 'ACTIVE' 
                WHERE paypal_subscription_id = ?
            ''', (paypal_sub_id,))
    
    def handle_payment_completed(self, resource: Dict, cursor):
        """Handle successful payment"""
        billing_agreement_id = resource.get('billing_agreement_id')
        if billing_agreement_id:
            cursor.execute('''
                UPDATE paypal_subscriptions 
                SET last_payment_date = CURRENT_TIMESTAMP,
                    failed_payment_count = 0
                WHERE paypal_subscription_id = ?
            ''', (billing_agreement_id,))
    
    def handle_payment_failed(self, resource: Dict, cursor):
        """Handle failed payment"""
        subscription_id = resource.get('id')
        if subscription_id:
            cursor.execute('''
                UPDATE paypal_subscriptions 
                SET failed_payment_count = failed_payment_count + 1
                WHERE paypal_subscription_id = ?
            ''', (subscription_id,))
            
            # Suspend after 3 failures
            cursor.execute('''
                UPDATE paypal_subscriptions 
                SET status = 'SUSPENDED'
                WHERE paypal_subscription_id = ? AND failed_payment_count >= 3
            ''', (subscription_id,))
    
    def verify_webhook_signature(self, webhook_data: Dict, headers: Dict) -> bool:
        """Verify PayPal webhook signature for security"""
        # Implement PayPal webhook signature verification
        # This is crucial for production security
        return True  # Simplified for example
    
    def process_monthly_overages(self):
        """Process overage billing for all customers (run monthly)"""
        from customer_resource_manager import CustomerResourceManager
        
        resource_manager = CustomerResourceManager()
        
        # Get current month period
        now = datetime.now()
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            period_end = period_start.replace(year=now.year + 1, month=1) - timedelta(days=1)
        else:
            period_end = period_start.replace(month=now.month + 1) - timedelta(days=1)
        
        # Get all active customers
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT c.customer_id 
            FROM customers c
            JOIN paypal_subscriptions ps ON c.customer_id = ps.customer_id
            WHERE ps.status = 'ACTIVE'
        ''')
        
        customers = cursor.fetchall()
        conn.close()
        
        for (customer_id,) in customers:
            # Get billing period data
            billing_period = resource_manager.aggregate_usage_for_billing(
                customer_id, period_start, period_end
            )
            
            if billing_period and billing_period.overage_requests > 0:
                # Create overage invoice
                success, result = self.create_overage_invoice(
                    customer_id, 
                    billing_period.overage_requests,
                    period_start, 
                    period_end
                )
                
                if success:
                    print(f"Created overage invoice for customer {customer_id}: {billing_period.overage_requests:,} requests")
                else:
                    print(f"Failed to create overage invoice for {customer_id}: {result}")

# Flask integration
def integrate_paypal_billing(app, customer_manager):
    """Integrate PayPal billing with Flask app"""
    
    # Initialize with your PayPal credentials
    paypal_manager = PayPalBillingManager(
        client_id="your_paypal_client_id",
        client_secret="your_paypal_client_secret",
        environment=PayPalEnvironment.SANDBOX,  # Change to LIVE for production
        webhook_id="your_webhook_id"
    )
    
    @app.route('/api/billing/plans')
    def get_billing_plans():
        """Get available billing plans"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT plan_id, name, description, monthly_price, request_limit, overage_rate
            FROM paypal_plans WHERE is_active = 1
        ''')
        
        plans = []
        for row in cursor.fetchall():
            plan_id, name, desc, price, limit, overage = row
            plans.append({
                'plan_id': plan_id,
                'name': name,
                'description': desc,
                'monthly_price': float(price),
                'request_limit': limit,
                'overage_rate': float(overage)
            })
        
        conn.close()
        return jsonify({'plans': plans})
    
    @app.route('/api/billing/subscribe', methods=['POST'])
    def create_subscription_endpoint():
        """Create PayPal subscription for customer"""
        data = request.get_json()
        customer_id = data.get('customer_id')
        plan_id = data.get('plan_id')
        
        # Get customer details
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT email, company_name FROM customers WHERE customer_id = ?
        ''', (customer_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return jsonify({'error': 'Customer not found'}), 404
        
        email, company_name = result
        
        success, approval_url = paypal_manager.create_subscription(
            customer_id, plan_id, email, company_name or "Customer"
        )
        
        if success:
            return jsonify({
                'success': True,
                'approval_url': approval_url,
                'message': 'Subscription created. Customer must approve via PayPal.'
            })
        else:
            return jsonify({'success': False, 'error': approval_url}), 400
    
    @app.route('/webhook/paypal', methods=['POST'])
    def paypal_webhook():
        """Handle PayPal webhook events"""
        webhook_data = request.get_json()
        headers = dict(request.headers)
        
        success = paypal_manager.handle_webhook(webhook_data, headers)
        
        if success:
            return jsonify({'status': 'processed'}), 200
        else:
            return jsonify({'status': 'error'}), 400
    
    @app.route('/api/billing/process-overages', methods=['POST'])
    def process_monthly_overages():
        """Manually trigger overage processing (or set up as cron job)"""
        try:
            paypal_manager.process_monthly_overages()
            return jsonify({'success': True, 'message': 'Overage processing completed'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    return paypal_manager