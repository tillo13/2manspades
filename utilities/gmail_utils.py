#!/usr/bin/env python3
"""
Gmail utilities for sending emails and notifications
100% self-contained - NO sibling imports allowed.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google.cloud import secretmanager
from os import path
import logging
from typing import List, Optional, Dict, Any

# =============================================================================
# GLOBAL VARIABLES - Email configuration
# =============================================================================

# Define the project ID and the secret IDs for username and app password
PROJECT_ID = 'kumori-404602'
GMAIL_USERNAME_SECRET_ID = 'KUMORI_GMAIL_USERNAME'
GMAIL_APP_PASSWORD_SECRET_ID = 'KUMORI_GMAIL_APP_PASSWORD'

# Email defaults
EMAIL_DEFAULTS = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 465,
    "default_from_name": "Kumori.ai",
    "use_ssl": True,
    "timeout_seconds": 30
}

# =============================================================================
# CORE FUNCTIONS
# =============================================================================

def get_secret_version(project_id: str, secret_id: str, version_id: str = "latest") -> str:
    """Get secret from Google Cloud Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode('UTF-8')

def get_gmail_credentials() -> Dict[str, str]:
    """Get Gmail credentials from Google Cloud Secret Manager."""
    return {
        'user': get_secret_version(PROJECT_ID, GMAIL_USERNAME_SECRET_ID),
        'password': get_secret_version(PROJECT_ID, GMAIL_APP_PASSWORD_SECRET_ID),
    }

def send_email(
    subject: str,
    body: str,
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    bcc_emails: Optional[List[str]] = None,
    attachment_paths: Optional[List[str]] = None,
    is_html: bool = False,
    from_name: str = None
) -> bool:
    """
    Send an email using Gmail SMTP.
    
    Args:
        subject: Email subject line
        body: Email body content
        to_emails: List of recipient email addresses
        cc_emails: List of CC email addresses (optional)
        bcc_emails: List of BCC email addresses (optional)
        attachment_paths: List of file paths to attach (optional)
        is_html: Whether the body is HTML format (default: False)
        from_name: Display name for sender (uses default if None)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if from_name is None:
        from_name = EMAIL_DEFAULTS["default_from_name"]
    
    try:
        # Get credentials
        gmail_credentials = get_gmail_credentials()
        gmail_user = gmail_credentials['user']
        gmail_password = gmail_credentials['password']
        
        # Create message
        message = MIMEMultipart()
        message['From'] = f'{from_name} <{gmail_user}>'
        message['To'] = ', '.join(to_emails)
        message['Subject'] = subject
        
        # Add CC and BCC if provided
        if cc_emails:
            message['Cc'] = ', '.join(cc_emails)
        if bcc_emails:
            message['Bcc'] = ', '.join(bcc_emails)
        
        # Attach body
        if is_html:
            message.attach(MIMEText(body, 'html'))
        else:
            message.attach(MIMEText(body, 'plain'))
        
        # Add attachments if provided
        if attachment_paths:
            for attachment_path in attachment_paths:
                if not path.exists(attachment_path):
                    logging.warning(f"Attachment file not found: {attachment_path}")
                    continue
                    
                part = MIMEBase('application', 'octet-stream')
                with open(attachment_path, 'rb') as file:
                    part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=path.basename(attachment_path)
                )
                message.attach(part)
        
        # Prepare recipient list (including CC and BCC for actual sending)
        all_recipients = to_emails.copy()
        if cc_emails:
            all_recipients.extend(cc_emails)
        if bcc_emails:
            all_recipients.extend(bcc_emails)
        
        # Send email
        smtp_server = EMAIL_DEFAULTS["smtp_server"]
        smtp_port = EMAIL_DEFAULTS["smtp_port"]
        timeout = EMAIL_DEFAULTS["timeout_seconds"]
        
        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=timeout) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(message, to_addrs=all_recipients)
            
        logging.info('Email sent successfully')
        print('Email sent successfully')
        return True
        
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        print(f"Failed to send email: {e}")
        return False

def send_simple_email(
    subject: str, 
    body: str, 
    to_email: str, 
    attachment_paths: Optional[List[str]] = None,
    is_html: bool = False
) -> bool:
    """
    Simplified function to send email to a single recipient.
    
    Args:
        subject: Email subject line
        body: Email body content
        to_email: Recipient email address
        attachment_paths: List of file paths to attach (optional)
        is_html: Whether the body is HTML format (default: False)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    return send_email(subject, body, [to_email], attachment_paths=attachment_paths, is_html=is_html)

def send_notification_email(
    title: str,
    message: str,
    recipient: str,
    priority: str = "normal",
    include_timestamp: bool = True
) -> bool:
    """
    Send a formatted notification email.
    
    Args:
        title: Notification title
        message: Notification message
        recipient: Email recipient
        priority: Priority level ("low", "normal", "high")
        include_timestamp: Whether to include timestamp
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    from datetime import datetime
    
    # Format subject based on priority
    priority_prefix = {"low": "ℹ️", "normal": "📨", "high": "🚨"}.get(priority, "📨")
    subject = f"{priority_prefix} {title}"
    
    # Format body
    body_parts = []
    if include_timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body_parts.append(f"Time: {timestamp}")
    
    body_parts.append(f"Message: {message}")
    
    if priority == "high":
        body_parts.append("\n⚠️ This is a high-priority notification.")
    
    body = "\n\n".join(body_parts)
    
    return send_simple_email(subject, body, recipient)

def send_pipeline_completion_email(
    project_name: str,
    recipient: str,
    success: bool,
    details: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Send pipeline completion notification email.
    
    Args:
        project_name: Name of the project/pipeline
        recipient: Email recipient
        success: Whether pipeline completed successfully
        details: Optional details dictionary
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    status = "✅ Completed Successfully" if success else "❌ Failed"
    subject = f"Pipeline {status}: {project_name}"
    
    body_parts = [
        f"Project: {project_name}",
        f"Status: {status}",
    ]
    
    if details:
        body_parts.append("\nDetails:")
        for key, value in details.items():
            body_parts.append(f"  {key}: {value}")
    
    body = "\n".join(body_parts)
    
    return send_simple_email(subject, body, recipient)

def get_email_defaults() -> Dict[str, Any]:
    """Get current email defaults."""
    return EMAIL_DEFAULTS.copy()

def update_email_defaults(**kwargs) -> None:
    """Update email defaults globally."""
    EMAIL_DEFAULTS.update(kwargs)
    logging.info(f"Updated email defaults: {kwargs}")

if __name__ == '__main__':
    # This module is meant to be imported, not run directly
    print("This is a utility module. Import it in your script to use the email functions.")
    print("Example:")
    print("from utilities.gmail_utils import send_email")
    print("send_email('Subject', 'Body', ['recipient@example.com'])")