import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4


REPOSITORY = Path(__file__).resolve().parents[2]


def private_path(value):
    path = Path(value).resolve(strict=True)
    if path.is_relative_to(REPOSITORY):
        raise ValueError("Private staging files must be kept outside the repository")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise ValueError("Private staging files and directories must deny group and other access")
    return path


class AccountMail:
    def __init__(self, *, mode="off", origin="", directory=None, smtp=None):
        if mode not in ("off", "capture", "smtp"):
            raise ValueError("Invalid account email mode")
        if mode != "off":
            origin = origin.rstrip("/")
            parsed = urlsplit(origin)
            local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
            if (not parsed.hostname or parsed.username or parsed.password or parsed.path
                    or parsed.query or parsed.fragment
                    or (parsed.scheme != "https" and not (mode == "capture" and local))):
                raise ValueError("Configure a trusted HTTPS origin for account links")
        self.mode = mode
        self.origin = origin
        self.directory = directory
        self.smtp = smtp

    @classmethod
    def from_environment(cls):
        mode = os.environ.get("KUDILEDGER_MAIL_MODE", "off")
        origin = os.environ.get("KUDILEDGER_PUBLIC_ORIGIN", "")
        if mode == "capture":
            directory = private_path(os.environ["KUDILEDGER_MAIL_CAPTURE_DIR"])
            if not directory.is_dir():
                raise ValueError("The capture directory must exist")
            return cls(mode=mode, origin=origin, directory=directory)
        if mode == "smtp":
            secret = private_path(os.environ["KUDILEDGER_SMTP_PASSWORD_FILE"])
            smtp = (
                os.environ["KUDILEDGER_SMTP_HOST"],
                int(os.environ.get("KUDILEDGER_SMTP_PORT", "465")),
                os.environ["KUDILEDGER_SMTP_USER"],
                secret,
                os.environ["KUDILEDGER_SMTP_FROM"],
            )
            return cls(mode=mode, origin=origin, smtp=smtp)
        return cls(mode=mode)

    def permits(self, email):
        return self.mode == "smtp" or (self.mode == "capture" and email.endswith(".test"))

    def send(self, purpose, email, token):
        if not self.permits(email):
            raise ValueError("Email delivery is disabled for this recipient")
        link = f"{self.origin}/app#{purpose}={token}"
        if self.mode == "capture":
            path = self.directory / (str(uuid4()) + ".json")
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                           "w", encoding="utf-8") as file:
                json.dump({"to": email, "purpose": purpose, "link": link}, file)
            return
        host, port, user, secret, sender = self.smtp
        message = EmailMessage()
        message["From"] = sender
        message["To"] = email
        message["Subject"] = "Set up your KudiLedger account" if purpose == "invite" else "Reset your KudiLedger password"
        message.set_content("Open this one-time link to continue:\n" + link +
                            "\nIf you did not request this, you can ignore this message.")
        with smtplib.SMTP_SSL(host, port, timeout=10, context=ssl.create_default_context()) as client:
            client.login(user, secret.read_text(encoding="utf-8").rstrip("\r\n"))
            client.send_message(message)
