"""Email delivery. SMTP when configured; otherwise writes .eml files to ./outbox (dev)."""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from ..config import get_settings

log = logging.getLogger("quik.mail")
OUTBOX = Path("outbox")


def _send_sync(msg: EmailMessage) -> None:
    s = get_settings()
    if not s.smtp_host:
        OUTBOX.mkdir(exist_ok=True)
        path = OUTBOX / f"{msg['To'].replace('@', '_at_')}-{abs(hash(msg['Subject'])) % 10**8}.eml"
        path.write_bytes(bytes(msg))
        log.info("SMTP not configured; wrote %s", path)
        return
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user and s.smtp_password:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send(to: str, subject: str, text: str, html: str | None = None,
               attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = get_settings().mail_from, to, subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    try:
        await asyncio.to_thread(_send_sync, msg)
    except Exception:  # never let mail failure break a booking
        log.exception("failed to send mail to %s", to)
