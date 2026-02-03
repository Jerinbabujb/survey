import os
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
    # 1. Configuration Setup
    host = host or os.environ.get("SMTP_HOST", "smtp.office365.com")
    port = port or int(os.environ.get("SMTP_PORT", 587))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD")
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    if not all([host, port, username, password, from_email]):
        raise ValueError("SMTP settings are incomplete. Check environment variables.")

    # 2. Build the Email Message
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content("This email requires HTML support.")
    msg.add_alternative(html_content, subtype="html")

    # 3. SMTP Initialization
    # For port 587, use_tls (Implicit TLS) is False, start_tls (Explicit TLS) is True
    smtp = SMTP(
        hostname=host,
        port=port,
        use_tls=False,      
        start_tls=use_tls,  
        timeout=30,
    )

    try:
        # 'async with' handles connection and STARTTLS automatically
        async with smtp:
            print(f"[DEBUG] Connected to {host}:{port}")

            # Office365 handling: bypass XOAUTH2 if using standard/app passwords
            # We check the set of supported methods directly
            if smtp.supported_auth_methods and "XOAUTH2" in smtp.supported_auth_methods:
                smtp.supported_auth_methods.discard("XOAUTH2")
                print("[DEBUG] Removed XOAUTH2 from supported methods.")

            print(f"[DEBUG] Logging in as {username}...")
            await smtp.login(username, password)
            
            print(f"[DEBUG] Sending email to {to_email}...")
            await smtp.send_message(msg)
            print(f"[DEBUG] Email sent successfully.")

    except Exception as e:
        print(f"[ERROR] Failed to send email: {type(e).__name__}: {e}")
        raise