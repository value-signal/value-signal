import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from pipeline.config import settings

SMTP_TIMEOUT_SECONDS = 15
SENDER_NAME = "Value Signal"
# 긴 해지 URL이 인코딩되면 메일 앱이 List-Unsubscribe를 인식하지 못한다.
MAIL_POLICY = SMTP.clone(max_line_length=998)

SendEmail = Callable[..., None]


class EmailError(Exception):
    pass


def _sender() -> str:
    """로그인 계정과 보낸 사람이 다르면 받는 쪽에서 DKIM 인증 실패로 거부한다."""
    if settings.smtp_user:
        return formataddr((SENDER_NAME, settings.smtp_user))
    return settings.alert_from


def build_message(
    to: str, subject: str, body: str, unsubscribe_url: str | None = None
) -> EmailMessage:
    sender = _sender()
    message = EmailMessage(policy=MAIL_POLICY)
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2])
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    message.set_content(body)
    return message


def _authenticate(smtp: smtplib.SMTP) -> None:
    """PLAIN으로만 인증한다.

    login()은 거절되면 다른 방식으로 재시도하는데, Gmail이 그때 연결을 끊어 535가 가려진다.
    """
    smtp.ehlo()
    smtp.user = settings.smtp_user
    smtp.password = settings.smtp_password
    smtp.auth("PLAIN", smtp.auth_plain)


def send_email(to: str, subject: str, body: str, unsubscribe_url: str | None = None) -> None:
    required = [("SMTP_HOST", settings.smtp_host)]
    if settings.smtp_tls:
        required += [("SMTP_USER", settings.smtp_user), ("SMTP_PASSWORD", settings.smtp_password)]
    else:
        required += [("ALERT_FROM", settings.alert_from)]
    missing = [name for name, value in required if not value]
    if missing:
        raise EmailError(f"메일 설정 없음: {', '.join(missing)}")

    message = build_message(to, subject, body, unsubscribe_url)
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            if settings.smtp_tls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                _authenticate(smtp)
            smtp.send_message(message)
    except smtplib.SMTPResponseException as error:
        # 응답 코드만 남긴다. 메시지에는 계정 정보가 섞일 수 있다.
        raise EmailError(f"{type(error).__name__} {error.smtp_code}") from error
    except (OSError, smtplib.SMTPException) as error:
        raise EmailError(type(error).__name__) from error
