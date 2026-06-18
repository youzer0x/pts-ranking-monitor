"""Gmail 送信（PTS ランキング通知）。Gmail API（HTTPS）方式。

クラウド環境は HTTP/HTTPS プロキシ経由のため SMTP(465) は通らない。代わりに
OAuth2 リフレッシュトークンでアクセストークンを取得し、Gmail API の
`users.messages.send`（HTTPS）でメールを送る。送信先ドメインは既定の
Trusted 許可リスト（*.googleapis.com）に含まれるため追加のネット許可は不要。

必要な環境変数:
  GMAIL_CLIENT_ID     … Google Cloud の OAuth クライアント ID
  GMAIL_CLIENT_SECRET … 同 クライアントシークレット
  GMAIL_REFRESH_TOKEN … get_gmail_token.py で一度だけ取得するリフレッシュトークン
  GMAIL_ADDRESS       … 送信元（自分の Gmail アドレス）
  NOTIFY_TO           … 送信先（省略時は GMAIL_ADDRESS）

scope は gmail.send のみで足りる。
"""
import os
import json
import base64
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _access_token():
    """リフレッシュトークンからアクセストークンを取得する（HTTPS）。"""
    data = urllib.parse.urlencode({
        "client_id": os.environ["GMAIL_CLIENT_ID"],
        "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
        "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def _build_raw(sender, recipient, session_date, count, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【PTS夜間値上がり】{session_date} 値上がり率ランキング（{count}社）"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(
        f"{session_date} の PTS ナイトタイム 値上がりランキング（{count}社）です。"
        "HTML 表示に対応したメーラーでご覧ください。", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_gmail(html_body, session_date, count):
    sender = os.environ["GMAIL_ADDRESS"]
    recipient = os.environ.get("NOTIFY_TO", sender)

    print(f"  Sending email to {recipient} via Gmail API ...")
    token = _access_token()
    payload = json.dumps({
        "raw": _build_raw(sender, recipient, session_date, count, html_body)
    }).encode()
    req = urllib.request.Request(
        SEND_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
    print(f"  Email sent. id={resp.get('id')}")
