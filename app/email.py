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
    """
    Send an email asynchronously using aiosmtplib.
    
    Automatically falls back to environment variables if parameters are not provided.
    Supports implicit SSL (port 465) and STARTTLS (port 587).
    """
    # Use environment variables if parameters are not provided
    host = host or os.environ.get("SMTP_HOST")
    port = port or int(os.environ.get("SMTP_PORT", 465))
    username = username or os.environ.get("SMTP_USERNAME")
    password = password or os.environ.get("SMTP_PASSWORD")
    use_tls = use_tls if use_tls is not None else os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    from_email = from_email or os.environ.get("SMTP_FROM_EMAIL")
    from_name = from_name or os.environ.get("SMTP_FROM_NAME", "Survey Bot")

    # Ensure all required parameters are set
    if not all([host, port, username, password, from_email]):
        raise ValueError("SMTP settings are incomplete. Please check your environment variables or arguments.")

    # Create the email message
    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(html_content, subtype="html")

    # Build the connection arguments
    send_kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "password": password,
        "timeout": 30,  # Increase timeout to avoid network delays
    }

    # Handle TLS correctly
    if port == 465:
        send_kwargs["use_tls"] = True  # Implicit SSL
    else:
        send_kwargs["start_tls"] = use_tls  # STARTTLS for port 587

    # Send the email
    try:
        await aiosmtplib.send(message, **send_kwargs)
        print(f"✅ Email sent successfully to {to_email}")
    except aiosmtplib.errors.SMTPConnectTimeoutError:
        print(f"❌ Connection timed out when sending email to {to_email}")
        raise
    except aiosmtplib.errors.SMTPException as smtp_err:
        print(f"❌ SMTP error occurred: {smtp_err}")
        raise
    except Exception as e:
        print(f"❌ Unexpected error occurred: {e}")
        raise
