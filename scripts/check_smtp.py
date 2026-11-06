"""Gmail 계정과 앱 비밀번호가 맞는지 확인한다. 입력값은 저장하거나 출력하지 않는다.

실행: uv run python -m scripts.check_smtp
"""
import getpass
import smtplib
import ssl

HOST = "smtp.gmail.com"
PORT = 587
APP_PASSWORD_LENGTH = 16


def main() -> None:
    user = input("Gmail 주소: ").strip()
    entered = getpass.getpass("앱 비밀번호 (입력이 보이지 않습니다): ")
    password = "".join(entered.split())

    print(f"입력 길이 {len(entered)}자, 공백 제거 후 {len(password)}자")
    if len(password) != APP_PASSWORD_LENGTH:
        print("앱 비밀번호는 16자입니다. 평소 비밀번호를 넣지 않았는지 확인해 주세요.")

    with smtplib.SMTP(HOST, PORT, timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.user = user
        smtp.password = password
        try:
            smtp.auth("PLAIN", smtp.auth_plain)
        except smtplib.SMTPAuthenticationError as error:
            print(f"로그인 실패: {error.smtp_code}")
            return
    print("로그인 성공: 이 주소와 16자리를 Vercel에 그대로 넣으면 됩니다.")


if __name__ == "__main__":
    main()
