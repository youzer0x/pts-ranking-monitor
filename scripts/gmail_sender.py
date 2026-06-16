"""Gmail 送信（PTS ランキング通知）。app password による SMTP_SSL。

環境変数: GMAIL_ADDRESS / GMAIL_APP_PASSWORD / NOTIFY_TO（省略時は送信元へ）。
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_gmail(html_body, session_date, count):
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_TO", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【PTS夜間値上がり】{session_date} 値上がりランキング（{count}社）"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(
        f"{session_date} の PTS ナイトタイム 値上がりランキング（{count}社）です。"
        "HTML 表示に対応したメーラーでご覧ください。", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"  Sending email to {recipient} ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(sender, password)
        server.send_message(msg)
    print("  Email sent.")
