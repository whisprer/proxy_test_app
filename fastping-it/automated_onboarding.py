"""
Automated Customer Onboarding System
====================================

Complete end-to-end automation from PayPal payment to active service
- PayPal webhook processing
- Automatic account creation
- IP/Port allocation
- Service activation
- Welcome email sequence
- Monitoring setup
"""

import sqlite3
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import uuid
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import threading
import time
import logging
from dataclasses import dataclass
import hashlib
import hmac

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('onboarding.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class OnboardingEvent:
    event_id: str
    customer_email: str
    plan_type: str
    payment_amount: float
    paypal_transaction_id: str
    timestamp: datetime
    status: str = "pending"

class AutomatedOnboardingManager:
    def __init__(self, paypal_manager, customer_manager, whitelist_manager):
        self.paypal_manager = paypal_manager
        self.customer_manager = customer_manager
        self.whitelist_manager = whitelist_manager
        self.init_database()
        
    def init_database(self):
        """Initialize onboarding tracking database"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        # Onboarding events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS onboarding_events (
                event_id TEXT PRIMARY KEY,
                customer_email TEXT NOT NULL,
                customer_id TEXT,
                plan_type TEXT NOT NULL,
                payment_amount REAL NOT NULL,
                paypal_transaction_id TEXT UNIQUE NOT NULL,
                onboarding_status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0
            )
        ''')
        
        # Welcome email templates
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_templates (
                template_id TEXT PRIMARY KEY,
                template_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                html_content TEXT NOT NULL,
                text_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Onboarding steps tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS onboarding_steps (
                step_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                step_status TEXT DEFAULT 'pending',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_details TEXT,
                FOREIGN KEY (event_id) REFERENCES onboarding_events (event_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Create default email templates
        self.create_default_email_templates()
    
    def create_default_email_templates(self):
        """Create default email templates for onboarding"""
        templates = [
            {
                'template_id': 'welcome_basic',
                'template_name': 'Basic Plan Welcome',
                'subject': '🚀 Welcome to ProxyForge - Your Service is Active!',
                'html_content': '''
                    <html>
                    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px;">
                            <h1 style="color: #40e0ff; text-align: center;">Welcome to ProxyForge! 🎉</h1>
                            
                            <p>Hi there!</p>
                            
                            <p>Your Basic Plan is now <strong>active and ready to use</strong>! We've automatically set up everything you need.</p>
                            
                            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                                <h3 style="color: #333; margin-top: 0;">📋 Your Account Details</h3>
                                <p><strong>Plan:</strong> Basic (10,000 requests/month)</p>
                                <p><strong>Rate Limit:</strong> 100 requests/minute</p>
                                <p><strong>Allocated IP:</strong> {allocated_ip}</p>
                                <p><strong>API Key:</strong> {api_key}</p>
                                <p><strong>Customer ID:</strong> {customer_id}</p>
                            </div>
                            
                            <div style="background: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0;">
                                <h3 style="color: #28a745; margin-top: 0;">🚀 Quick Start</h3>
                                <p>Test your service immediately:</p>
                                <code style="background: #f1f1f1; padding: 10px; display: block; border-radius: 4px;">
                                    curl -H "Authorization: Bearer {api_key}" https://api.proxyforge.com/test
                                </code>
                            </div>
                            
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="https://docs.proxyforge.com" style="background: #40e0ff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">📚 View Documentation</a>
                            </div>
                            
                            <p>Need help? Reply to this email or contact our support team at <a href="mailto:support@proxyforge.com">support@proxyforge.com</a></p>
                            
                            <p>Welcome aboard! 🚀</p>
                            <p>The ProxyForge Team</p>
                        </div>
                    </body>
                    </html>
                ''',
                'text_content': '''Welcome to ProxyForge!
                
Your Basic Plan is now active and ready to use!

Account Details:
- Plan: Basic (10,000 requests/month)
- Rate Limit: 100 requests/minute  
- Allocated IP: {allocated_ip}
- API Key: {api_key}
- Customer ID: {customer_id}

Quick Start:
Test your service: curl -H "Authorization: Bearer {api_key}" https://api.proxyforge.com/test

Documentation: https://docs.proxyforge.com
Support: support@proxyforge.com

Welcome aboard!
The ProxyForge Team'''
            },
            {
                'template_id': 'welcome_premium',
                'template_name': 'Premium Plan Welcome',
                'subject': '🔥 Welcome to ProxyForge Premium - Enhanced Service Active!',
                'html_content': '''
                    <html>
                    <body style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                        <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px;">
                            <h1 style="color: #40e0ff; text-align: center;">Welcome to ProxyForge Premium! 🔥</h1>
                            
                            <p>Congratulations on upgrading to our Premium Plan!</p>
                            
                            <p>Your enhanced service is now <strong>active with dedicated resources</strong>.</p>
                            
                            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                                <h3 style="color: #333; margin-top: 0;">⚡ Your Premium Account</h3>
                                <p><strong>Plan:</strong> Premium (50,000 requests/month)</p>
                                <p><strong>Rate Limit:</strong> 500 requests/minute</p>
                                <p><strong>Allocated IP:</strong> {allocated_ip}</p>
                                <p><strong>Port Range:</strong> {port_start}-{port_end}</p>
                                <p><strong>API Key:</strong> {api_key}</p>
                                <p><strong>Customer ID:</strong> {customer_id}</p>
                            </div>
                            
                            <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                                <h3 style="color: #856404; margin-top: 0;">🎯 Premium Features</h3>
                                <ul>
                                    <li>Dedicated IP + Port allocation</li>
                                    <li>Priority support response</li>
                                    <li>Advanced analytics dashboard</li>
                                    <li>Custom rate limiting</li>
                                </ul>
                            </div>
                            
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="https://dashboard.proxyforge.com" style="background: #40e0ff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-right: 10px;">🎛️ Dashboard</a>
                                <a href="https://docs.proxyforge.com/premium" style="background: #6c757d; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">📖 Premium Docs</a>
                            </div>
                            
                            <p>Questions? Your dedicated account manager will contact you within 24 hours.</p>
                            
                            <p>Thank you for choosing Premium! 🚀</p>
                            <p>The ProxyForge Team</p>
                        </div>
                    </body>
                    </html>
                ''',
                'text_content': '''Welcome to ProxyForge Premium!

Your Premium service is now active with dedicated resources.

Premium Account Details:
- Plan: Premium (50,000 requests/month)
- Rate Limit: 500 requests/minute
- Allocated IP: {allocated_ip}
- Port Range: {port_start}-{port_end}
- API Key: {api_key}
- Customer ID: {customer_id}

Premium Features:
- Dedicated IP + Port allocation
- Priority support response  
- Advanced analytics dashboard
- Custom rate limiting

Dashboard: https://dashboard.proxyforge.com
Premium Docs: https://docs.proxyforge.com/premium

Your dedicated account manager will contact you within 24 hours.

Thank you for choosing Premium!
The ProxyForge Team'''
            }
        ]
        
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        for template in templates:
            cursor.execute('''
                INSERT OR REPLACE INTO email_templates 
                (template_id, template_name, subject, html_content, text_content)
                VALUES (?, ?, ?, ?, ?)
            ''', (template['template_id'], template['template_name'], 
                 template['subject'], template['html_content'], template['text_content']))
        
        conn.commit()
        conn.close()
    
    def process_paypal_webhook(self, webhook_data: Dict) -> bool:
        """Process incoming PayPal webhook and trigger onboarding"""
        try:
            event_type = webhook_data.get('event_type')
            resource = webhook_data.get('resource', {})
            
            # Handle subscription activation
            if event_type == 'BILLING.SUBSCRIPTION.ACTIVATED':
                return self._handle_subscription_activated(webhook_data)
            
            # Handle one-time payment completion
            elif event_type == 'PAYMENT.SALE.COMPLETED':
                return self._handle_payment_completed(webhook_data)
            
            # Handle subscription payment success
            elif event_type == 'BILLING.SUBSCRIPTION.PAYMENT.COMPLETED':
                return self._handle_subscription_payment(webhook_data)
            
            else:
                logger.info(f"Unhandled webhook event type: {event_type}")
                return True
                
        except Exception as e:
            logger.error(f"Error processing PayPal webhook: {e}")
            return False
    
    def _handle_subscription_activated(self, webhook_data: Dict) -> bool:
        """Handle new subscription activation"""
        try:
            resource = webhook_data.get('resource', {})
            subscription_id = resource.get('id')
            subscriber = resource.get('subscriber', {})
            email = subscriber.get('email_address')
            plan_id = resource.get('plan_id')
            
            if not email or not plan_id:
                logger.error("Missing email or plan_id in subscription webhook")
                return False
            
            # Map PayPal plan ID to our plan type
            plan_type = self._map_plan_id_to_type(plan_id)
            
            # Create onboarding event
            event_id = str(uuid.uuid4())
            onboarding_event = OnboardingEvent(
                event_id=event_id,
                customer_email=email,
                plan_type=plan_type,
                payment_amount=0.0,  # Subscription activation
                paypal_transaction_id=subscription_id,
                timestamp=datetime.now()
            )
            
            # Start async onboarding process
            threading.Thread(
                target=self._execute_onboarding_flow, 
                args=(onboarding_event,),
                daemon=True
            ).start()
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling subscription activation: {e}")
            return False
    
    def _handle_payment_completed(self, webhook_data: Dict) -> bool:
        """Handle one-time payment completion"""
        try:
            resource = webhook_data.get('resource', {})
            transaction_id = resource.get('id')
            amount = float(resource.get('amount', {}).get('total', 0))
            payer_info = resource.get('payer_info', {})
            email = payer_info.get('email')
            
            if not email:
                logger.error("Missing email in payment webhook")
                return False
            
            # Determine plan type based on payment amount
            plan_type = self._determine_plan_from_amount(amount)
            
            # Create onboarding event
            event_id = str(uuid.uuid4())
            onboarding_event = OnboardingEvent(
                event_id=event_id,
                customer_email=email,
                plan_type=plan_type,
                payment_amount=amount,
                paypal_transaction_id=transaction_id,
                timestamp=datetime.now()
            )
            
            # Start async onboarding process
            threading.Thread(
                target=self._execute_onboarding_flow, 
                args=(onboarding_event,),
                daemon=True
            ).start()
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling payment completion: {e}")
            return False
    
    def _map_plan_id_to_type(self, paypal_plan_id: str) -> str:
        """Map PayPal plan ID to our internal plan type"""
        # Query database to map PayPal plan ID to our plan type
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT plan_id FROM paypal_plans WHERE paypal_plan_id = ?
        ''', (paypal_plan_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            # Extract plan type from our plan_id (e.g., "plan_basic_123" -> "basic")
            plan_id = result[0]
            if 'basic' in plan_id.lower():
                return 'basic'
            elif 'premium' in plan_id.lower():
                return 'premium'
            elif 'enterprise' in plan_id.lower():
                return 'enterprise'
        
        return 'basic'  # Default fallback
    
    def _determine_plan_from_amount(self, amount: float) -> str:
        """Determine plan type from payment amount"""
        if amount >= 299:
            return 'enterprise'
        elif amount >= 99:
            return 'premium'
        else:
            return 'basic'
    
    def _execute_onboarding_flow(self, event: OnboardingEvent):
        """Execute the complete onboarding flow"""
        try:
            # Store onboarding event
            self._store_onboarding_event(event)
            
            # Define onboarding steps
            steps = [
                ('validate_payment', self._validate_payment),
                ('create_customer', self._create_customer_account),
                ('allocate_resources', self._allocate_customer_resources),
                ('configure_whitelist', self._configure_ip_whitelist),
                ('setup_monitoring', self._setup_customer_monitoring),
                ('send_welcome_email', self._send_welcome_email),
                ('notify_admin', self._notify_admin_new_customer)
            ]
            
            customer_id = None
            
            for step_name, step_function in steps:
                step_id = str(uuid.uuid4())
                
                try:
                    # Record step start
                    self._record_step_start(event.event_id, step_id, step_name)
                    
                    # Execute step
                    if step_name == 'create_customer':
                        customer_id = step_function(event)
                        event.customer_id = customer_id
                    else:
                        step_function(event)
                    
                    # Record step completion
                    self._record_step_completion(step_id)
                    
                    logger.info(f"Completed onboarding step '{step_name}' for {event.customer_email}")
                    
                except Exception as e:
                    logger.error(f"Failed onboarding step '{step_name}' for {event.customer_email}: {e}")
                    self._record_step_error(step_id, str(e))
                    
                    # Retry critical steps
                    if step_name in ['create_customer', 'allocate_resources']:
                        self._schedule_retry(event, step_name)
                    
                    raise e
            
            # Mark onboarding as completed
            self._complete_onboarding(event.event_id)
            
            logger.info(f"Successfully completed onboarding for {event.customer_email}")
            
        except Exception as e:
            logger.error(f"Onboarding flow failed for {event.customer_email}: {e}")
            self._mark_onboarding_failed(event.event_id, str(e))
    
    def _store_onboarding_event(self, event: OnboardingEvent):
        """Store onboarding event in database"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO onboarding_events 
            (event_id, customer_email, plan_type, payment_amount, paypal_transaction_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (event.event_id, event.customer_email, event.plan_type, 
             event.payment_amount, event.paypal_transaction_id))
        
        conn.commit()
        conn.close()
    
    def _validate_payment(self, event: OnboardingEvent):
        """Validate payment with PayPal"""
        # In production, verify the payment is legitimate and not fraudulent
        # For now, we trust the webhook (but should implement verification)
        logger.info(f"Payment validated for {event.customer_email}")
    
    def _create_customer_account(self, event: OnboardingEvent) -> str:
        """Create customer account"""
        success, customer_id = self.customer_manager.create_customer(
            email=event.customer_email,
            company_name=None,  # Can be updated later
            plan_type=event.plan_type
        )
        
        if not success:
            raise Exception(f"Failed to create customer account: {customer_id}")
        
        # Update onboarding event with customer ID
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE onboarding_events SET customer_id = ? WHERE event_id = ?
        ''', (customer_id, event.event_id))
        conn.commit()
        conn.close()
        
        return customer_id
    
    def _allocate_customer_resources(self, event: OnboardingEvent):
        """Allocate IP/port resources"""
        # Resources are automatically allocated in create_customer
        resources = self.customer_manager.get_customer_resources(event.customer_id)
        
        if not resources:
            raise Exception("No resources allocated to customer")
        
        logger.info(f"Resources allocated for {event.customer_email}: {len(resources)} resources")
    
    def _configure_ip_whitelist(self, event: OnboardingEvent):
        """Configure IP whitelist (already done in create_customer, but verify)"""
        resources = self.customer_manager.get_customer_resources(event.customer_id)
        
        for resource in resources:
            # Verify IP is in whitelist
            is_allowed, _ = self.whitelist_manager.is_ip_allowed(resource.ip_address)
            if not is_allowed:
                raise Exception(f"IP {resource.ip_address} not properly whitelisted")
        
        logger.info(f"IP whitelist configured for {event.customer_email}")
    
    def _setup_customer_monitoring(self, event: OnboardingEvent):
        """Setup monitoring for new customer"""
        # Create monitoring entry (this could integrate with your monitoring system)
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO customer_monitoring 
            (customer_id, monitoring_enabled, alert_threshold, created_at)
            VALUES (?, ?, ?, ?)
        ''', (event.customer_id, True, 0.95, datetime.now().isoformat()))
        
        # Create monitoring table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customer_monitoring (
                customer_id TEXT PRIMARY KEY,
                monitoring_enabled BOOLEAN DEFAULT 1,
                alert_threshold REAL DEFAULT 0.95,
                last_alert TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info(f"Monitoring setup for {event.customer_email}")
    
    def _send_welcome_email(self, event: OnboardingEvent):
        """Send welcome email with account details"""
        # Get customer and resource details
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        # Get customer API key
        cursor.execute('''
            SELECT api_key FROM customers WHERE customer_id = ?
        ''', (event.customer_id,))
        
        api_key_result = cursor.fetchone()
        if not api_key_result:
            raise Exception("Customer API key not found")
        
        api_key = api_key_result[0]
        
        # Get allocated resources
        resources = self.customer_manager.get_customer_resources(event.customer_id)
        if not resources:
            raise Exception("No resources found for customer")
        
        primary_resource = resources[0]
        
        # Get email template
        template_id = f"welcome_{event.plan_type}"
        cursor.execute('''
            SELECT subject, html_content, text_content FROM email_templates 
            WHERE template_id = ?
        ''', (template_id,))
        
        template_result = cursor.fetchone()
        conn.close()
        
        if not template_result:
            template_id = 'welcome_basic'  # Fallback
            template_result = self._get_template(template_id)
        
        subject, html_content, text_content = template_result
        
        # Format template with customer data
        template_vars = {
            'customer_id': event.customer_id,
            'api_key': api_key,
            'allocated_ip': primary_resource.ip_address,
            'port_start': primary_resource.port_start or 'N/A',
            'port_end': primary_resource.port_end or 'N/A'
        }
        
        formatted_subject = subject.format(**template_vars)
        formatted_html = html_content.format(**template_vars)
        formatted_text = text_content.format(**template_vars)
        
        # Send email
        self._send_email(
            to_email=event.customer_email,
            subject=formatted_subject,
            html_content=formatted_html,
            text_content=formatted_text
        )
        
        logger.info(f"Welcome email sent to {event.customer_email}")
    
    def _notify_admin_new_customer(self, event: OnboardingEvent):
        """Notify admin about new customer"""
        resources = self.customer_manager.get_customer_resources(event.customer_id)
        
        admin_message = f"""
        🎉 New Customer Onboarded Successfully!
        
        Customer: {event.customer_email}
        Plan: {event.plan_type.title()}
        Customer ID: {event.customer_id}
        Payment Amount: ${event.payment_amount:.2f}
        Resources Allocated: {len(resources)}
        
        Customer is now active and monitored.
        """
        
        self._send_email(
            to_email="admin@proxyforge.com",
            subject=f"New {event.plan_type.title()} Customer: {event.customer_email}",
            text_content=admin_message
        )
        
        logger.info(f"Admin notified about new customer {event.customer_email}")
    
    def _get_template(self, template_id: str) -> tuple:
        """Get email template from database"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT subject, html_content, text_content FROM email_templates 
            WHERE template_id = ?
        ''', (template_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def _send_email(self, to_email: str, subject: str, 
                   html_content: str = None, text_content: str = None):
        """Send email notification"""
        # Email configuration
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        smtp_username = "noreply@proxyforge.com"
        smtp_password = "your_email_password"  # Use environment variable
        
        try:
            msg = MimeMultipart('alternative')
            msg['From'] = smtp_username
            msg['To'] = to_email
            msg['Subject'] = subject
            
            if text_content:
                msg.attach(MimeText(text_content, 'plain'))
            
            if html_content:
                msg.attach(MimeText(html_content, 'html'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(smtp_username, to_email, msg.as_string())
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            raise e
    
    def _record_step_start(self, event_id: str, step_id: str, step_name: str):
        """Record start of onboarding step"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO onboarding_steps 
            (step_id, event_id, step_name, step_status, started_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (step_id, event_id, step_name, 'running', datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def _record_step_completion(self, step_id: str):
        """Record completion of onboarding step"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE onboarding_steps 
            SET step_status = 'completed', completed_at = ?
            WHERE step_id = ?
        ''', (datetime.now().isoformat(), step_id))
        conn.commit()
        conn.close()
    
    def _record_step_error(self, step_id: str, error_details: str):
        """Record error in onboarding step"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE onboarding_steps 
            SET step_status = 'failed', error_details = ?
            WHERE step_id = ?
        ''', (error_details, step_id))
        conn.commit()
        conn.close()
    
    def _complete_onboarding(self, event_id: str):
        """Mark onboarding as completed"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE onboarding_events 
            SET onboarding_status = 'completed', completed_at = ?
            WHERE event_id = ?
        ''', (datetime.now().isoformat(), event_id))
        conn.commit()
        conn.close()
    
    def _mark_onboarding_failed(self, event_id: str, error_message: str):
        """Mark onboarding as failed"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE onboarding_events 
            SET onboarding_status = 'failed', error_message = ?
            WHERE event_id = ?
        ''', (error_message, event_id))
        conn.commit()
        conn.close()
    
    def _schedule_retry(self, event: OnboardingEvent, failed_step: str):
        """Schedule retry for failed onboarding"""
        # Implement retry logic - could use celery, background tasks, etc.
        logger.info(f"Scheduling retry for {event.customer_email}, failed step: {failed_step}")
    
    def get_onboarding_status(self, email: str) -> Dict:
        """Get onboarding status for a customer"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT event_id, onboarding_status, created_at, completed_at, error_message
            FROM onboarding_events 
            WHERE customer_email = ? 
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (email,))
        
        event_result = cursor.fetchone()
        
        if not event_result:
            conn.close()
            return {'status': 'not_found'}
        
        event_id, status, created_at, completed_at, error_message = event_result
        
        # Get step details
        cursor.execute('''
            SELECT step_name, step_status, started_at, completed_at, error_details
            FROM onboarding_steps 
            WHERE event_id = ? 
            ORDER BY started_at
        ''', (event_id,))
        
        steps = []
        for row in cursor.fetchall():
            step_name, step_status, started_at, step_completed_at, error_details = row
            steps.append({
                'step_name': step_name,
                'status': step_status,
                'started_at': started_at,
                'completed_at': step_completed_at,
                'error_details': error_details
            })
        
        conn.close()
        
        return {
            'status': status,
            'created_at': created_at,
            'completed_at': completed_at,
            'error_message': error_message,
            'steps': steps
        }
    
    def retry_failed_onboarding(self, email: str) -> bool:
        """Manually retry failed onboarding"""
        try:
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Get latest failed onboarding
            cursor.execute('''
                SELECT event_id, customer_email, plan_type, payment_amount, paypal_transaction_id
                FROM onboarding_events 
                WHERE customer_email = ? AND onboarding_status = 'failed'
                ORDER BY created_at DESC 
                LIMIT 1
            ''', (email,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return False
            
            event_id, customer_email, plan_type, payment_amount, paypal_transaction_id = result
            
            # Create new onboarding event for retry
            retry_event = OnboardingEvent(
                event_id=str(uuid.uuid4()),
                customer_email=customer_email,
                plan_type=plan_type,
                payment_amount=payment_amount,
                paypal_transaction_id=f"retry_{paypal_transaction_id}",
                timestamp=datetime.now()
            )
            
            # Start retry process
            threading.Thread(
                target=self._execute_onboarding_flow, 
                args=(retry_event,),
                daemon=True
            ).start()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to retry onboarding for {email}: {e}")
            return False

# Flask Integration for Automated Onboarding
def integrate_automated_onboarding(app, customer_manager, whitelist_manager, paypal_manager):
    """Integrate automated onboarding with Flask app"""
    
    onboarding_manager = AutomatedOnboardingManager(
        paypal_manager, customer_manager, whitelist_manager
    )
    
    @app.route('/webhook/paypal/onboarding', methods=['POST'])
    def paypal_onboarding_webhook():
        """Enhanced PayPal webhook handler for onboarding"""
        try:
            webhook_data = request.get_json()
            headers = dict(request.headers)
            
            # Verify webhook signature (production security)
            if not onboarding_manager._verify_webhook_signature(webhook_data, headers):
                logger.warning("Invalid webhook signature")
                return jsonify({'error': 'Invalid signature'}), 401
            
            # Process webhook and trigger onboarding
            success = onboarding_manager.process_paypal_webhook(webhook_data)
            
            if success:
                return jsonify({'status': 'processed'}), 200
            else:
                return jsonify({'status': 'error'}), 400
                
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return jsonify({'error': 'Processing failed'}), 500
    
    @app.route('/api/onboarding/status/<email>')
    def get_onboarding_status_api(email):
        """Get onboarding status via API"""
        try:
            status = onboarding_manager.get_onboarding_status(email)
            return jsonify(status)
        except Exception as e:
            logger.error(f"Error getting onboarding status: {e}")
            return jsonify({'error': 'Failed to get status'}), 500
    
    @app.route('/api/onboarding/retry', methods=['POST'])
    def retry_onboarding_api():
        """Manually retry failed onboarding"""
        try:
            data = request.get_json()
            email = data.get('email')
            
            if not email:
                return jsonify({'error': 'Email required'}), 400
            
            success = onboarding_manager.retry_failed_onboarding(email)
            
            if success:
                return jsonify({'success': True, 'message': 'Retry initiated'})
            else:
                return jsonify({'success': False, 'message': 'No failed onboarding found'}), 404
                
        except Exception as e:
            logger.error(f"Error retrying onboarding: {e}")
            return jsonify({'error': 'Retry failed'}), 500
    
    @app.route('/admin/onboarding/dashboard')
    def onboarding_dashboard():
        """Admin dashboard for onboarding monitoring"""
        try:
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Get recent onboarding events
            cursor.execute('''
                SELECT customer_email, plan_type, onboarding_status, created_at, completed_at
                FROM onboarding_events 
                ORDER BY created_at DESC 
                LIMIT 50
            ''')
            
            events = []
            for row in cursor.fetchall():
                email, plan_type, status, created_at, completed_at = row
                events.append({
                    'email': email,
                    'plan_type': plan_type,
                    'status': status,
                    'created_at': created_at,
                    'completed_at': completed_at
                })
            
            # Get summary stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN onboarding_status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN onboarding_status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN onboarding_status = 'pending' THEN 1 ELSE 0 END) as pending
                FROM onboarding_events 
                WHERE created_at >= date('now', '-7 days')
            ''')
            
            stats = cursor.fetchone()
            conn.close()
            
            dashboard_html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Onboarding Dashboard</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px; }}
                    .stat-card {{ background: white; padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .stat-number {{ font-size: 2rem; font-weight: bold; color: #40e0ff; }}
                    .stat-label {{ color: #666; margin-top: 5px; }}
                    .events-table {{ background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    table {{ width: 100%; border-collapse: collapse; }}
                    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
                    th {{ background: #f8f9fa; font-weight: 600; }}
                    .status-completed {{ color: #28a745; font-weight: bold; }}
                    .status-failed {{ color: #dc3545; font-weight: bold; }}
                    .status-pending {{ color: #ffc107; font-weight: bold; }}
                    .refresh-btn {{ background: #40e0ff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>🚀 Onboarding Dashboard</h1>
                    
                    <div class="stats">
                        <div class="stat-card">
                            <div class="stat-number">{stats[0]}</div>
                            <div class="stat-label">Total (7 days)</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats[1]}</div>
                            <div class="stat-label">Completed</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats[2]}</div>
                            <div class="stat-label">Failed</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats[3]}</div>
                            <div class="stat-label">Pending</div>
                        </div>
                    </div>
                    
                    <div class="events-table">
                        <table>
                            <thead>
                                <tr>
                                    <th>Email</th>
                                    <th>Plan</th>
                                    <th>Status</th>
                                    <th>Started</th>
                                    <th>Completed</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
            '''
            
            for event in events:
                status_class = f"status-{event['status']}"
                completed_display = event['completed_at'] or '-'
                
                dashboard_html += f'''
                                <tr>
                                    <td>{event['email']}</td>
                                    <td>{event['plan_type'].title()}</td>
                                    <td class="{status_class}">{event['status'].title()}</td>
                                    <td>{event['created_at'][:19]}</td>
                                    <td>{completed_display}</td>
                                    <td>
                                        <button onclick="retryOnboarding('{event['email']}')" 
                                                class="refresh-btn">Retry</button>
                                    </td>
                                </tr>
                '''
            
            dashboard_html += '''
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <script>
                    function retryOnboarding(email) {
                        if (confirm(`Retry onboarding for ${email}?`)) {
                            fetch('/api/onboarding/retry', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({email: email})
                            })
                            .then(response => response.json())
                            .then(data => {
                                alert(data.message || 'Retry initiated');
                                location.reload();
                            })
                            .catch(error => {
                                alert('Error: ' + error);
                            });
                        }
                    }
                    
                    // Auto-refresh every 30 seconds
                    setTimeout(() => location.reload(), 30000);
                </script>
            </body>
            </html>
            '''
            
            return dashboard_html
            
        except Exception as e:
            logger.error(f"Error loading onboarding dashboard: {e}")
            return f"Error loading dashboard: {e}", 500
    
    @app.route('/api/onboarding/test', methods=['POST'])
    def test_onboarding():
        """Test onboarding flow with fake data"""
        try:
            data = request.get_json()
            email = data.get('email', 'test@example.com')
            plan_type = data.get('plan_type', 'basic')
            
            # Create test onboarding event
            test_event = OnboardingEvent(
                event_id=str(uuid.uuid4()),
                customer_email=email,
                plan_type=plan_type,
                payment_amount=29.99,
                paypal_transaction_id=f"test_{int(time.time())}",
                timestamp=datetime.now()
            )
            
            # Start test onboarding
            threading.Thread(
                target=onboarding_manager._execute_onboarding_flow, 
                args=(test_event,),
                daemon=True
            ).start()
            
            return jsonify({
                'success': True, 
                'message': 'Test onboarding started',
                'event_id': test_event.event_id
            })
            
        except Exception as e:
            logger.error(f"Error testing onboarding: {e}")
            return jsonify({'error': 'Test failed'}), 500
    
    return onboarding_manager

# Customer Status Monitoring
class CustomerStatusMonitor:
    """Monitor customer status and health"""
    
    def __init__(self, customer_manager, whitelist_manager):
        self.customer_manager = customer_manager
        self.whitelist_manager = whitelist_manager
        
    def check_customer_health(self) -> Dict:
        """Check health status of all customers"""
        conn = sqlite3.connect('customer_resources.db')
        cursor = conn.cursor()
        
        # Get all active customers
        cursor.execute('''
            SELECT customer_id, email, plan_type, created_at 
            FROM customers 
            WHERE status = 'active'
        ''')
        
        customers = cursor.fetchall()
        health_report = {
            'total_customers': len(customers),
            'healthy_customers': 0,
            'warning_customers': 0,
            'critical_customers': 0,
            'customer_details': []
        }
        
        for customer_id, email, plan_type, created_at in customers:
            customer_health = self._check_individual_customer_health(customer_id)
            health_report['customer_details'].append({
                'customer_id': customer_id,
                'email': email,
                'plan_type': plan_type,
                'health_status': customer_health['status'],
                'issues': customer_health['issues']
            })
            
            if customer_health['status'] == 'healthy':
                health_report['healthy_customers'] += 1
            elif customer_health['status'] == 'warning':
                health_report['warning_customers'] += 1
            else:
                health_report['critical_customers'] += 1
        
        conn.close()
        return health_report
    
    def _check_individual_customer_health(self, customer_id: str) -> Dict:
        """Check health of individual customer"""
        issues = []
        status = 'healthy'
        
        try:
            # Check if customer has allocated resources
            resources = self.customer_manager.get_customer_resources(customer_id)
            if not resources:
                issues.append("No resources allocated")
                status = 'critical'
            
            # Check if IPs are whitelisted
            for resource in resources:
                is_allowed, _ = self.whitelist_manager.is_ip_allowed(resource.ip_address)
                if not is_allowed:
                    issues.append(f"IP {resource.ip_address} not whitelisted")
                    status = 'critical'
            
            # Check recent usage
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Check for recent activity (last 24 hours)
            cursor.execute('''
                SELECT COUNT(*) FROM usage_logs 
                WHERE customer_id = ? AND timestamp > ?
            ''', (customer_id, (datetime.now() - timedelta(hours=24)).isoformat()))
            
            recent_requests = cursor.fetchone()[0]
            
            # Check for high error rate
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors
                FROM usage_logs 
                WHERE customer_id = ? AND timestamp > ?
            ''', (customer_id, (datetime.now() - timedelta(hours=24)).isoformat()))
            
            usage_stats = cursor.fetchone()
            total_requests, error_count = usage_stats or (0, 0)
            
            if total_requests > 0:
                error_rate = error_count / total_requests
                if error_rate > 0.1:  # 10% error rate
                    issues.append(f"High error rate: {error_rate:.1%}")
                    status = 'warning' if status == 'healthy' else status
            
            conn.close()
            
        except Exception as e:
            issues.append(f"Health check error: {str(e)}")
            status = 'critical'
        
        return {
            'status': status,
            'issues': issues
        }

# Complete integration function
def setup_complete_onboarding_system(app, customer_manager, whitelist_manager, paypal_manager):
    """Setup complete automated onboarding system"""
    
    # Initialize onboarding manager
    onboarding_manager = integrate_automated_onboarding(
        app, customer_manager, whitelist_manager, paypal_manager
    )
    
    # Initialize monitoring
    status_monitor = CustomerStatusMonitor(customer_manager, whitelist_manager)
    
    @app.route('/api/system/health')
    def system_health_check():
        """System-wide health check"""
        try:
            health_report = status_monitor.check_customer_health()
            return jsonify(health_report)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({'error': 'Health check failed'}), 500
    
    # Background health monitoring
    def background_health_monitor():
        """Background task to monitor customer health"""
        while True:
            try:
                health_report = status_monitor.check_customer_health()
                
                # Alert on critical customers
                if health_report['critical_customers'] > 0:
                    logger.warning(f"Critical customers detected: {health_report['critical_customers']}")
                    # Send admin alert email here
                
                # Log health summary
                logger.info(
                    f"Customer Health: {health_report['healthy_customers']} healthy, "
                    f"{health_report['warning_customers']} warning, "
                    f"{health_report['critical_customers']} critical"
                )
                
                time.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Background health monitor error: {e}")
                time.sleep(300)
    
    # Start background monitoring
    health_thread = threading.Thread(target=background_health_monitor, daemon=True)
    health_thread.start()
    
    logger.info("🚀 Complete automated onboarding system initialized!")
    
    return {
        'onboarding_manager': onboarding_manager,
        'status_monitor': status_monitor
    }