import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from email.policy import SMTP

from pipeline.config import settings

SMTP_TIMEOUT_SECONDS = 15
# 긴 해지 URL이 인코딩되면 메일 앱이 List-Unsubscribe를 인식하지 못한다.
MAIL_POLICY = SMTP.clone(max_line_length=998)

SendEmail = Callable[..., None]


class EmailError(Exception):
    pass


def build_message(
    to: str, subject: str, body: str, unsubscribe_url: str | None = None
) -> EmailMessage:
    message = EmailMessage(policy=MAIL_POLICY)
    message["From"] = settings.alert_from
    message["To"] = to
    message["Subject"] = subject
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    message.set_content(body)
    return message


def send_email(to: str, subject: str, body: str, unsubscribe_url: str | None = None) -> None:
    if not settings.smtp_host or not settings.alert_from:
        raise EmailError("메일 설정이 없습니다")

    message = build_message(to, subject, body, unsubscribe_url)
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailError(type(error).__name__) from error
