import os
import smtplib
from email.mime.text import MIMEText


def send_email(html_content, subject="Daily Stock Report", to_email=None):
    sender_email = os.getenv("EMAIL_USER")
    sender_pass = os.getenv("EMAIL_PASS")
    recipient_email = to_email or sender_email  # default to self-send if no recipient specified

    # Build message
    msg = MIMEText(html_content, "html")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_pass)
            server.send_message(msg)
        print("✅ Email sent successfully.")
    except smtplib.SMTPAuthenticationError as e:
        print("❌ SMTP Authentication failed.")
        print("📎 Hint:", e.smtp_error.decode())
        raise
    except Exception as e:
        print("❌ Failed to send email.")
        raise