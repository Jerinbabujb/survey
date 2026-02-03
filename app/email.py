import os
import socket
from aiosmtplib import SMTP
from email.message import EmailMessage

async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    host: str = None,
    port: int = None,
    username: str = None,
    password: str = None,
    use_tls: bool = True,
    from_email: str = None,
    from_name: str = None,
):
    host = host or os.environ.get("SMTP_HOST", "smtp.office365.com")
    port = port or int(os.environ.get("SMTP_PORT", 587))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD")
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("Please use an HTML compatible email client.")
    msg.add_alternative(html_content, subtype="html")

    # Initialize SMTP with explicit STARTTLS setting for Port 587
    smtp = SMTP(
        hostname=host, 
        port=port, 
        use_tls=False,      # False because 587 starts unencrypted
        start_tls=True,     # True because Office365 REQUIRES upgrading to TLS
        timeout=60
    )

    try:
        await smtp.connect()
        
        # Manually discard XOAUTH2 if the library tries to use it
        if smtp.supported_auth_methods:
            if "XOAUTH2" in smtp.supported_auth_methods:
                smtp.supported_auth_methods.discard("XOAUTH2")

        print(f"[DEBUG] Attempting login for {username}...")
        await smtp.login(username, password)
        
        await smtp.send_message(msg)
        print(f"[DEBUG] Email sent successfully to {to_email}")
        await smtp.quit()

    except Exception as e:
        print(f"[ERROR] SMTP Error: {e}")
        # Re-raise so the application knows the invite failed
        raise