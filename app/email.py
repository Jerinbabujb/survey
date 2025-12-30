import os
import aiosmtplib
from email.message import EmailMessage

async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    host: str = None,
    port: int = None,
    username: str = None,
    password: str = None,
    use_tls: bool = None,
    from_email: str = None,
    from_name: str = None,
):
    # Fallback to env vars
    host = host or os.environ.get("SMTP_HOST")
    port = int(port or os.environ.get("SMTP_PORT", 587))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD")
    use_tls = use_tls if use_tls is not None else os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(html_content, subtype="html")

    # HostGator specific: Port 465 uses use_tls (Implicit SSL)
    # Port 587 uses start_tls (Explicit TLS)
    is_ssl_port = (port == 465)

    try:
        smtp_client = aiosmtplib.SMTP(
            hostname=host,
            port=port,
            use_tls=is_ssl_port,  # True for 465
            start_tls=not is_ssl_port and use_tls, # True for 587
        )
        
        async with smtp_client:
            # We add 'hostname' here to identify our server to HostGator
            await smtp_client.login(username, password)
            await smtp_client.send_message(message)
            
        print(f"✅ Email actually sent and confirmed for {to_email}")
    except Exception as e:
        print(f"❌ SMTP Error: {e}")
        raise