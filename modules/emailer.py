import os
import smtplib
from email.mime.text import MIMEText
import logging

def send_email(html_content, subject="Daily Stock Report", to_email=None):
    sender_email = os.getenv("EMAIL_USER")
    sender_pass = os.getenv("EMAIL_PASS")
    recipient_email = to_email or sender_email

    msg = MIMEText(html_content, "html")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        logging.info("Email sent successfully")
    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"SMTP Authentication failed: {e.smtp_error.decode()}")
        raise
    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")
        raise