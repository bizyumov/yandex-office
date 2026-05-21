# Yandex SMTP XOAUTH2 Send Reference

## SMTP Connection

- Server: `smtp.yandex.com` (config key `smtp.server`)
- Port: `465` SSL (config key `smtp.port`)
- Auth: XOAUTH2 SASL mechanism
- Auth string: `user={email}\x01auth=Bearer {token}\x01\x01` (identical to IMAP)

## XOAUTH2 SMTP Auth Pattern

```python
import base64, smtplib, ssl

auth_string = f"user={email}\x01auth=Bearer {token}\x01\x01"
context = ssl.create_default_context()
conn = smtplib.SMTP_SSL(server, port, context=context, timeout=30)
conn.ehlo()
code, message = conn.docmd("AUTH", "XOAUTH2 " + base64.b64encode(auth_string.encode()).decode())
# code 235 = auth success, 535 = auth failed
```

Note: `smtplib.SMTP_SSL` parameter is `context=`, not `ssl_context=`.

## App Password Fallback

When OAuth2 tokens are unavailable, Yandex app passwords work with standard `conn.login(user, password)`.
App passwords are created at Yandex ID → Security → App passwords. Must enable 2FA first.
App passwords activate 2-3 hours after creation.

Prerequisites in Yandex Mail settings:
- Enable "Access via IMAP from imap.yandex.ru"
- Enable "App passwords and OAuth tokens"

## Email Headers — Importance and Priority

Do NOT guess header values. Use these exact RFC specifications:

| Header | Values | Standard |
|--------|--------|----------|
| `X-Priority` | `1` (highest) to `5` (lowest) | Non-RFC de facto standard |
| `Importance` | `high`, `normal`, `low` | RFC 4356 |
| `Priority` | `urgent`, `normal`, `non-urgent` | RFC 2156 |
| `X-MSMail-Priority` | `High`, `Normal`, `Low` | Microsoft extension |

For high importance, set ALL of these:
```python
msg["X-Priority"] = "1"
msg["Importance"] = "high"
msg["Priority"] = "urgent"
```

## Email Headers — Read Receipt (MDN)

Per RFC 3798 (Message Disposition Notification):

```python
msg["Disposition-Notification-To"] = sender_email
```

**Caveat**: Read receipts are client-side. Yandex webmail may not send MDN responses.
The recipient's client decides whether to notify. This header REQUESTS a receipt — it does not guarantee one.

Do NOT add `Return-Receipt-To` or `X-Confirm-Reading-To` — these are non-standard and widely ignored.

## Email with Attachments

Use `email.mime.multipart.MIMEMultipart` for mixed content:

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

msg = MIMEMultipart()
msg["From"] = sender
msg["To"] = recipient
msg["Subject"] = subject

msg.attach(MIMEText(body, "plain", "utf-8"))

with open(filepath, "rb") as f:
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(f.read())
    encoders.encode_base64(attachment)
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)
```

## IMAP Folder Check (Sent Mail)

Yandex IMAP folder names: `INBOX`, `Sent`, `Drafts`, `Spam`, `Trash`, `Outbox`.

Sent messages are NOT automatically saved to the Sent folder when sending via SMTP.
If sent-mail persistence is needed, either:
1. IMAP APPEND to Sent folder after SMTP send, or
2. Use `mail-readwrite` scope which may auto-save (Yandex-specific behavior).

## Testing SMTP Code with Decorator

The `@yandex_api_method` decorator wraps methods with auth token dispatch.
In unit tests, bypass the decorator by calling the original function:

```python
# Build a real YandexApiContext (not MagicMock — decorator reads real attributes)
from common.api import YandexApiContext, TokenRef

ctx = YandexApiContext(
    account=None,
    data_dir=Path("/tmp/test"),
    config={"smtp": {"server": "smtp.yandex.com", "port": 465}},
    session=MagicMock(),
    token_ref=TokenRef(token="t", client_id="c", source_key="k", good_at=None, bad_at=None),
    token_data={"email": "user@example.com"},
)

# Call the unwrapped original method
original = sender._connect_smtp.__wrapped__
result = original(sender, ctx)
```

MagicMock objects fail because the decorator dispatch reads `ctx.account`, `ctx.data_dir`,
`ctx.config`, `ctx.session` — all of which must be real attributes, not mock auto-generated ones.
