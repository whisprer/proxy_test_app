"""
Automated Billing Scheduler
===========================

Background scheduler for automated billing operations
- Monthly overage processing
- Subscription status checks
- Failed payment retries
- Usage analytics and reporting
"""

import schedule
import time
import threading
from datetime import datetime, timedelta
import sqlite3
from typing import List, Dict
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('billing_scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BillingScheduler:
    def __init__(self, paypal_manager, customer_manager):
        self.paypal_manager = paypal_manager
        self.customer_manager = customer_manager
        self.running = False
        self.scheduler_thread = None
        
    def start_scheduler(self):
        """Start the background billing scheduler"""
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        # Schedule monthly overage processing
        schedule.every().month.at("02:00").do(self.process_monthly_overages)
        
        # Daily subscription health checks
        schedule.every().day.at("06:00").do(self.check_subscription_health)
        
        # Weekly usage reports
        schedule.every().monday.at("09:00").do(self.generate_weekly_reports)
        
        # Daily cleanup tasks
        schedule.every().day.at("03:00").do(self.daily_cleanup)
        
        # Hourly resource cleanup (from your existing system)
        schedule.every().hour.do(self.customer_manager.cleanup_expired_resources)
        
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("Billing scheduler started successfully")
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self.running = False
        schedule.clear()
        logger.info("Billing scheduler stopped")
    
    def _run_scheduler(self):
        """Internal scheduler loop"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)
    
    def process_monthly_overages(self):
        """Process overage billing for all customers"""
        logger.info("Starting monthly overage processing")
        
        try:
            # Get current billing period
            now = datetime.now()
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                period_end = period_start.replace(year=now.year + 1, month=1) - timedelta(days=1)
            else:
                period_end = period_start.replace(month=now.month + 1) - timedelta(days=1)
            
            # Get all active subscriptions
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT c.customer_id, c.email, c.company_name, ps.plan_id
                FROM customers c
                JOIN paypal_subscriptions ps ON c.customer_id = ps.customer_id
                WHERE ps.status = 'ACTIVE'
            ''')
            
            active_customers = cursor.fetchall()
            conn.close()
            
            overage_count = 0
            total_overage_amount = 0
            
            for customer_id, email, company_name, plan_id in active_customers:
                try:
                    # Calculate usage for billing period
                    billing_period = self.customer_manager.aggregate_usage_for_billing(
                        customer_id, period_start, period_end
                    )
                    
                    if billing_period and billing_period.overage_requests > 0:
                        # Create overage invoice
                        success, result = self.paypal_manager.create_overage_invoice(
                            customer_id,
                            billing_period.overage_requests,
                            period_start,
                            period_end
                        )
                        
                        if success:
                            overage_count += 1
                            total_overage_amount += float(billing_period.overage_cost)
                            logger.info(
                                f"Created overage invoice for {email}: "
                                f"{billing_period.overage_requests:,} requests, "
                                f"${billing_period.overage_cost:.2f}"
                            )
                            
                            # Send notification email to customer
                            self.send_overage_notification(
                                email, company_name, billing_period
                            )
                        else:
                            logger.error(f"Failed to create overage invoice for {customer_id}: {result}")
                            
                except Exception as e:
                    logger.error(f"Error processing overage for customer {customer_id}: {e}")
            
            # Send summary to admin
            self.send_admin_summary({
                'period_start': period_start,
                'period_end': period_end,
                'customers_processed': len(active_customers),
                'overage_invoices_created': overage_count,
                'total_overage_amount': total_overage_amount
            })
            
            logger.info(
                f"Monthly overage processing completed: "
                f"{overage_count} invoices, ${total_overage_amount:.2f} total"
            )
            
        except Exception as e:
            logger.error(f"Monthly overage processing failed: {e}")
            self.send_admin_alert("Monthly Overage Processing Failed", str(e))
    
    def check_subscription_health(self):
        """Daily check for subscription issues"""
        logger.info("Running subscription health check")
        
        try:
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Check for subscriptions with failed payments
            cursor.execute('''
                SELECT customer_id, failed_payment_count, last_payment_date
                FROM paypal_subscriptions 
                WHERE status = 'ACTIVE' AND failed_payment_count > 0
            ''')
            
            failed_payments = cursor.fetchall()
            
            # Check for subscriptions approaching suspension (2 failed payments)
            cursor.execute('''
                SELECT c.email, c.company_name, ps.failed_payment_count
                FROM customers c
                JOIN paypal_subscriptions ps ON c.customer_id = ps.customer_id
                WHERE ps.failed_payment_count = 2 AND ps.status = 'ACTIVE'
            ''')
            
            at_risk_customers = cursor.fetchall()
            
            # Check for expired subscriptions that should be cleaned up
            cursor.execute('''
                SELECT customer_id FROM paypal_subscriptions 
                WHERE status = 'EXPIRED' 
                AND last_payment_date < ?
            ''', ((datetime.now() - timedelta(days=7)).isoformat(),))
            
            expired_for_cleanup = cursor.fetchall()
            
            conn.close()
            
            # Send alerts for at-risk customers
            if at_risk_customers:
                for email, company_name, failed_count in at_risk_customers:
                    self.send_payment_reminder(email, company_name, failed_count)
            
            # Clean up long-expired subscriptions
            for (customer_id,) in expired_for_cleanup:
                self.cleanup_expired_customer(customer_id)
            
            logger.info(
                f"Subscription health check completed: "
                f"{len(failed_payments)} with failed payments, "
                f"{len(at_risk_customers)} at risk, "
                f"{len(expired_for_cleanup)} cleaned up"
            )
            
        except Exception as e:
            logger.error(f"Subscription health check failed: {e}")
    
    def generate_weekly_reports(self):
        """Generate weekly usage and billing reports"""
        logger.info("Generating weekly reports")
        
        try:
            week_ago = datetime.now() - timedelta(days=7)
            
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            # Get weekly usage stats
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT customer_id) as active_customers,
                    COUNT(*) as total_requests,
                    AVG(response_time_ms) as avg_response_time,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count
                FROM usage_logs 
                WHERE timestamp >= ?
            ''', (week_ago.isoformat(),))
            
            weekly_stats = cursor.fetchone()
            
            # Get revenue stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as invoices_sent,
                    SUM(overage_amount) as total_overage_revenue
                FROM overage_invoices 
                WHERE sent_at >= ?
            ''', (week_ago.isoformat(),))
            
            revenue_stats = cursor.fetchone()
            
            # Get top customers by usage
            cursor.execute('''
                SELECT c.email, c.plan_type, COUNT(*) as requests
                FROM usage_logs ul
                JOIN customers c ON ul.customer_id = c.customer_id
                WHERE ul.timestamp >= ?
                GROUP BY c.customer_id, c.email, c.plan_type
                ORDER BY requests DESC
                LIMIT 10
            ''', (week_ago.isoformat(),))
            
            top_customers = cursor.fetchall()
            
            conn.close()
            
            # Format and send report
            report_data = {
                'week_ending': datetime.now().strftime('%Y-%m-%d'),
                'weekly_stats': weekly_stats,
                'revenue_stats': revenue_stats, 
                'top_customers': top_customers
            }
            
            self.send_weekly_report(report_data)
            
            logger.info("Weekly report generated and sent")
            
        except Exception as e:
            logger.error(f"Weekly report generation failed: {e}")
    
    def daily_cleanup(self):
        """Daily maintenance tasks"""
        logger.info("Running daily cleanup tasks")
        
        try:
            # Clean up old payment events (keep 90 days)
            cutoff_date = (datetime.now() - timedelta(days=90)).isoformat()
            
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM payment_events WHERE processed_at < ?
            ''', (cutoff_date,))
            
            deleted_events = cursor.rowcount
            
            # Clean up old usage logs (keep 1 year)
            usage_cutoff = (datetime.now() - timedelta(days=365)).isoformat()
            
            cursor.execute('''
                DELETE FROM usage_logs WHERE timestamp < ?
            ''', (usage_cutoff,))
            
            deleted_usage = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            logger.info(f"Daily cleanup: {deleted_events} events, {deleted_usage} usage logs deleted")
            
        except Exception as e:
            logger.error(f"Daily cleanup failed: {e}")
    
    def cleanup_expired_customer(self, customer_id: str):
        """Clean up resources for expired customer"""
        try:
            # Release allocated resources
            resources = self.customer_manager.get_customer_resources(customer_id)
            for resource in resources:
                # Remove from whitelist
                from proxy_test_app import whitelist_manager
                whitelist_manager.remove_ip(resource.ip_address)
            
            # Deactivate customer
            conn = sqlite3.connect('customer_resources.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE customers SET status = 'expired' WHERE customer_id = ?
            ''', (customer_id,))
            cursor.execute('''
                UPDATE resource_allocations SET is_active = 0 WHERE customer_id = ?
            ''', (customer_id,))
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up expired customer: {customer_id}")
            
        except Exception as e:
            logger.error(f"Failed to cleanup customer {customer_id}: {e}")
    
    def send_overage_notification(self, email: str, company_name: str, billing_period):
        """Send overage notification to customer"""
        try:
            subject = f"Usage Overage Notice - {billing_period.period_start.strftime('%B %Y')}"
            
            message = f"""
            Dear {company_name or 'Valued Customer'},
            
            Your proxy service usage for {billing_period.period_start.strftime('%B %Y')} exceeded your plan limits.
            
            Plan Usage: {billing_period.total_requests - billing_period.overage_requests:,} requests (included)
            Overage Usage: {billing_period.overage_requests:,} requests
            Overage Charge: ${billing_period.overage_cost:.2f}
            
            An invoice has been sent to your PayPal account for the overage amount.
            
            Consider upgrading your plan to avoid future overage charges.
            
            Best regards,
            Your Proxy Service Team
            """
            
            self.send_email(email, subject, message)
            
        except Exception as e:
            logger.error(f"Failed to send overage notification to {email}: {e}")
    
    def send_payment_reminder(self, email: str, company_name: str, failed_count: int):
        """Send payment failure reminder"""
        try:
            subject = "Payment Issue - Action Required"
            
            message = f"""
            Dear {company_name or 'Valued Customer'},
            
            We've detected {failed_count} failed payment attempt(s) on your account.
            
            Please update your payment method in PayPal to avoid service interruption.
            
            After 3 failed payments, your service will be temporarily suspended.
            
            Update payment: https://www.paypal.com/billing
            
            Best regards,
            Your Proxy Service Team
            """
            
            self.send_email(email, subject, message)
            
        except Exception as e:
            logger.error(f"Failed to send payment reminder to {email}: {e}")
    
    def send_admin_summary(self, summary_data: Dict):
        """Send billing summary to admin"""
        try:
            subject = f"Monthly Billing Summary - {summary_data['period_start'].strftime('%B %Y')}"
            
            message = f"""
            Monthly Billing Processing Summary
            
            Period: {summary_data['period_start'].strftime('%B %d')} - {summary_data['period_end'].strftime('%B %d, %Y')}
            
            Total Customers Processed: {summary_data['customers_processed']}
            Overage Invoices Created: {summary_data['overage_invoices_created']}
            Total Overage Revenue: ${summary_data['total_overage_amount']:.2f}
            
            Processing completed successfully.
            """
            
            self.send_email("admin@yourservice.com", subject, message)
            
        except Exception as e:
            logger.error(f"Failed to send admin summary: {e}")
    
    def send_admin_alert(self, subject: str, message: str):
        """Send alert to admin"""
        try:
            full_message = f"""
            ALERT: {subject}
            
            {message}
            
            Time: {datetime.now().isoformat()}
            
            Please investigate immediately.
            """
            
            self.send_email("admin@yourservice.com", f"ALERT: {subject}", full_message)
            
        except Exception as e:
            logger.error(f"Failed to send admin alert: {e}")
    
    def send_weekly_report(self, report_data: Dict):
        """Send weekly usage report"""
        try:
            weekly_stats = report_data['weekly_stats']
            revenue_stats = report_data['revenue_stats']
            top_customers = report_data['top_customers']
            
            subject = f"Weekly Report - {report_data['week_ending']}"
            
            message = f"""
            Weekly Service Report - {report_data['week_ending']}
            
            === Usage Statistics ===
            Active Customers: {weekly_stats[0] or 0}
            Total Requests: {weekly_stats[1] or 0:,}
            Average Response Time: {weekly_stats[2] or 0:.2f}ms
            Error Count: {weekly_stats[3] or 0}
            
            === Revenue Statistics ===
            Overage Invoices Sent: {revenue_stats[0] or 0}
            Total Overage Revenue: ${revenue_stats[1] or 0:.2f}
            
            === Top Customers by Usage ===
            """
            
            for email, plan, requests in top_customers:
                message += f"{email} ({plan}): {requests:,} requests\n"
            
            self.send_email("admin@yourservice.com", subject, message)
            
        except Exception as e:
            logger.error(f"Failed to send weekly report: {e}")
    
    def send_email(self, to_email: str, subject: str, message: str):
        """Send email notification"""
        # Configure your SMTP settings
        smtp_server = "smtp.gmail.com"  # or your SMTP server
        smtp_port = 587
        smtp_username = "noreply@yourservice.com"
        smtp_password = "your_email_password"
        
        try:
            msg = MimeMultipart()
            msg['From'] = smtp_username
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MimeText(message, 'plain'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            text = msg.as_string()
            server.sendmail(smtp_username, to_email, text)
            server.quit()
            
            logger.info(f"Email sent to {to_email}: {subject}")
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")

# Integration with your main app
def setup_billing_automation(app, paypal_manager, customer_manager):
    """Setup automated billing scheduler"""
    
    scheduler = BillingScheduler(paypal_manager, customer_manager)
    
    # Start scheduler on app startup
    @app.before_first_request
    def start_scheduler():
        scheduler.start_scheduler()
    
    # Manual trigger endpoints for testing
    @app.route('/admin/trigger/monthly-billing', methods=['POST'])
    def trigger_monthly_billing():
        try:
            scheduler.process_monthly_overages()
            return jsonify({'success': True, 'message': 'Monthly billing processed'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/admin/trigger/health-check', methods=['POST']) 
    def trigger_health_check():
        try:
            scheduler.check_subscription_health()
            return jsonify({'success': True, 'message': 'Health check completed'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/admin/trigger/weekly-report', methods=['POST'])
    def trigger_weekly_report():
        try:
            scheduler.generate_weekly_reports()
            return jsonify({'success': True, 'message': 'Weekly report generated'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    return scheduler