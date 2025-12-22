import asyncio
from email.message import EmailMessage
from typing import Optional

import aiosmtplib


async def send_email(
    *,
    host: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
    use_tls: bool,
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    html_content: str,
) -> None:
    message = EmailMessage()
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content("This email requires an HTML capable client.")
    message.add_alternative(html_content, subtype="html")

    send_kwargs = {
        "hostname": host,
        "port": port,
        "username": username or None,
        "password": password or None,
    }

    if use_tls:
        await aiosmtplib.send(message, use_tls=True, **send_kwargs)
    else:
        await aiosmtplib.send(message, start_tls=False, **send_kwargs)


def send_email_blocking(**kwargs) -> None:
    asyncio.run(send_email(**kwargs))
