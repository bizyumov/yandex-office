# Mail SMTP sending

Use this reference when implementing, debugging, or operating Yandex Mail SMTP send support in `yandex-office`.

## Purpose

`mail/scripts/send_email.py` sends email through Yandex Mail SMTP. It supports:

- app-password LOGIN authentication as the primary path;
- managed OAuth2 XOAUTH2 as fallback;
- plain or HTML bodies;
- `To`, `Cc`, `Bcc`, `Reply-To`;
- JSON or text CLI output.

## Yandex prerequisites for app-password SMTP

App-password SMTP requires the Yandex account to allow mail-program access and app passwords.

1. In Yandex Mail settings open `https://mail.yandex.ru/#setup/client`.
2. Enable IMAP access: "С сервера imap.yandex.ru по протоколу IMAP".
3. Enable "Пароли приложений и OAuth-токены".
4. Save settings.
5. Enable 2FA at `https://id.yandex.ru/security`.
6. Create an app password at `https://id.yandex.ru/security/app-passwords`:
   - type: "Почта";
   - copy the generated 12-character password once.
7. Store credentials in `mail-credentials.env` in one of the supported locations.

Example file shape only; never expose real values in logs or chat:

```env
YANDEX_MAIL_USER=user@yandex.ru
YANDEX_MAIL_APP_PASSWORD=<app-password>
```

Credential lookup order:

1. `{data_dir}/mail-credentials.env`
2. `$HERMES_AGENT_SECRETS_DIR/mail-credentials.env`
3. `{agent_dir}/secrets/mail-credentials.env`

## SMTP and IMAP endpoints

SMTP send:

- server: `smtp.yandex.com`
- port: `465`
- protocol: `SMTP_SSL` / TLS from connection start
- authentication: LOGIN with app-password, or XOAUTH2 with OAuth token

IMAP reference:

- server: `imap.yandex.com`
- port: `993`
- protocol: SSL
- authentication: XOAUTH2 with OAuth token

## Auth dispatch design

The safe design is:

1. `_connect_smtp()` is undecorated and is the single dispatch entry point.
2. It first tries app-password credentials without invoking managed OAuth dispatch.
3. If no app-password credentials are available, it builds a Yandex API context and calls the decorated OAuth method.
4. `_connect_smtp_oauth2()` is the only method decorated with `@yandex_api_method("mail.smtp.send", one_of=["mail:imap_full", "mail:imap_ro"])`.

Pattern:

```python
def _connect_smtp(self, *, account=None) -> SmtpSendResult:
    creds = _load_app_password(self.data_dir)
    if creds is not None:
        return _connect_smtp_app_password(...)

    ctx = self._api_context(account=account)
    return self._connect_smtp_oauth2(ctx=ctx)

@yandex_api_method("mail.smtp.send", one_of=["mail:imap_full", "mail:imap_ro"])
def _connect_smtp_oauth2(self, ctx: YandexApiContext) -> SmtpSendResult:
    email_addr, token = self._mail_credentials(ctx)
    ...
```

Avoid decorating `_connect_smtp()` itself. The dispatcher binds the context to a concrete token and can fail or become ambiguous if the method also needs to check app-password credentials first.

XOAUTH2 SMTP auth string format:

```text
user={email}\x01auth=Bearer {token}\x01\x01
```

## CLI examples

Run from a normal workspace CWD and pass full script path and `--data-dir`/`--account` when appropriate.

```bash
python3 <full-path-to-yandex-office>/mail/scripts/send_email.py \
  --to user@example.com \
  --subject "Hello" \
  --body "Hi"

python3 <full-path-to-yandex-office>/mail/scripts/send_email.py \
  --to a@b.com \
  --cc c@d.com \
  --reply-to reply@e.com \
  --subject "Re: Topic" \
  --body "Reply"

python3 <full-path-to-yandex-office>/mail/scripts/send_email.py \
  --to a@b.com \
  --subject "Report" \
  --body "<h1>Hello</h1>" \
  --content-type html

python3 <full-path-to-yandex-office>/mail/scripts/send_email.py \
  --to a@b.com \
  --subject "Report" \
  --body-file report.txt

python3 <full-path-to-yandex-office>/mail/scripts/send_email.py \
  --to a@b.com \
  --subject "Test" \
  --body "OK" \
  --format json
```

## Unit-test pitfalls

OAuth2-decorated methods should not be tested with arbitrary `MagicMock` contexts through the real decorator. The dispatcher checks for real `YandexApiContext` values.

For unit tests of OAuth2 method internals, call the undecorated function via `__wrapped__`:

```python
original = sender._connect_smtp_oauth2.__wrapped__
result = original(sender, ctx)
```

For tests of dispatch priority, mock `_connect_smtp_oauth2` as a bound method instead of trying to drive the decorator through a mocked context:

```python
with patch("send_email._load_app_password", return_value=None):
    with patch.object(sender, "_connect_smtp_oauth2") as mock_oauth2:
        mock_oauth2.return_value = SmtpSendResult(conn=mock_conn, sender_email="...")
        result = sender._connect_smtp()
```

CLI tests should assert the integer returned by `main()` (`0`/`1`) rather than expecting `SystemExit`.

## High-importance and read-receipt headers

For high-priority mail:

```text
X-Priority: 1
Importance: high
```

- `X-Priority: 1` is non-standard but widely supported and appears as high priority in many clients.
- `Importance: high` is standardized by RFC 4356 and recognized by common mail clients.

Read-receipt request:

```text
Disposition-Notification-To: sender@example.com
```

Yandex SMTP preserves this header, but observed Outlook delivery did not produce a read notification. Do not rely on this mechanism for confirmed reading.

Python example:

```python
from email.message import EmailMessage

msg = EmailMessage()
msg["From"] = "sender@example.com"
msg["To"] = "recipient@example.com"
msg["Subject"] = "Urgent"
msg["X-Priority"] = "1"
msg["Importance"] = "high"
msg["Disposition-Notification-To"] = "sender@example.com"
msg.set_content("Body text")
```

## Delivered-header observations and spam signals

Observed Yandex incoming headers for legitimate mail may include:

```text
X-Yandex-Spam: 1
DKIM-Signature: pass
Authentication-Results: dkim=pass
X-Yandex-Fwd: 1
```

Empirical observations for `X-Yandex-Spam`:

- `1`: delivered as not spam in observed legitimate cases;
- `4`: spam in observed forum/community mail cases.

There is no official Yandex documentation for this header in this reference. Treat these as observations, not a contract.

Deliverability recommendations:

1. Configure DKIM for the sender domain.
2. Configure SPF for the sender domain.
3. Avoid spam-like subject/body patterns.
4. `X-Yandex-Spam: 1` is a normal observed result for legitimate mail.
5. `X-Yandex-Spam: 4` is a strong warning that Yandex classified the message as spam.
