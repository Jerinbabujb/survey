import os
import socket
from aiosmtplib import SMTP
from email.message import EmailMessage
from aiosmtplib.errors import SMTPAuthenticationError, SMTPException

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
    # 1. Configuration Setup
    host = host or os.environ.get("SMTP_HOST", "smtp.office365.com")
    port = port or int(os.environ.get("SMTP_PORT", 587))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD") # USE YOUR APP PASSWORD HERE
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    if not all([host, port, username, password, from_email]):
        raise ValueError("SMTP settings are incomplete. Check environment variables.")

    # 2. Build the Email Message
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    
    # Standard headers to prevent spam flagging
    msg["Message-ID"] = f"<{os.urandom(16).hex()}@{socket.gethostname()}>"
    
    msg.set_content("This email requires HTML support.")
    msg.add_alternative(html_content, subtype="html")

    # 3. SMTP Initialization
    # Office365 on Port 587 requires start_tls=True
    smtp = SMTP(
        hostname=host,
        port=port,
        use_tls=False, 
        start_tls=True,
        timeout=30,
    )

    try:
        print(f"[DEBUG] Connecting to {host}:{port}...")
        await smtp.connect()

        # Office365 handling: Explicitly discard XOAUTH2 
        # because we are using an App Password (Basic Auth)
        if smtp.supported_auth_methods:
            if "XOAUTH2" in smtp.supported_auth_methods:
                smtp.supported_auth_methods.discard("XOAUTH2")
            print(f"[DEBUG] Supported Auth Methods: {smtp.supported_auth_methods}")

        print(f"[DEBUG] Attempting login for {username} using App Password...")
        await smtp.login(username, password)
        
        print(f"[DEBUG] Sending message to {to_email}...")
        await smtp.send_message(msg)
        
        print(f"[DEBUG] Email sent successfully.")
        await smtp.quit()

    except SMTPAuthenticationError as e:
        print(f"[ERROR] Authentication Failed (535).")
        print(f"[REASON] This is usually because 'Authenticated SMTP' is disabled in M365 Admin for this user.")
        print(f"[DETAILS] {e}")
        raise
    except Exception as e:
        print(f"[ERROR] Unexpected email error: {type(e).__name__}: {e}")
        raise