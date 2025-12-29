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
    # Fallback to environment variables if arguments are not provided
    host = host or os.environ.get("SMTP_HOST")
    port = port or int(os.environ.get("SMTP_PORT", 587))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD")
    use_tls = use_tls if use_tls is not None else os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    if not all([host, port, username, password, from_email]):
        raise ValueError("SMTP settings are incomplete. Please check your environment variables or arguments.")

    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(html_content, subtype="html")

    send_kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "password": password,
        "start_tls": use_tls,
    }

    try:
        await aiosmtplib.send(message, **send_kwargs)
        print(f"Email sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        raise
