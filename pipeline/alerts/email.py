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
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.smtp_host),
            ("SMTP_USER", settings.smtp_user),
            ("SMTP_PASSWORD", settings.smtp_password),
            ("ALERT_FROM", settings.alert_from),
        )
        if not value and (name != "SMTP_USER" and name != "SMTP_PASSWORD" or settings.smtp_tls)
    ]
    if missing:
        raise EmailError(f"메일 설정 없음: {', '.join(missing)}")

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
    except smtplib.SMTPResponseException as error:
        # 응답 코드만 남긴다. 메시지에는 계정 정보가 섞일 수 있다.
        raise EmailError(f"{type(error).__name__} {error.smtp_code}") from error
    except (OSError, smtplib.SMTPException) as error:
        raise EmailError(type(error).__name__) from error
