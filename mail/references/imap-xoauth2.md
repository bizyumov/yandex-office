# IMAP XOAUTH2 Protocol Notes

## Authentication Flow

1. Obtain OAuth token via Yandex OAuth (run `python3 <full-path-to-yandex-skills>/scripts/oauth_setup.py ...` from the agent workspace CWD)
2. Connect to `imap.yandex.com:993` over TLS
3. Authenticate with XOAUTH2 SASL mechanism:

```
AUTH_STRING = "user={email}\x01auth=Bearer {token}\x01\x01"
```

The auth string is base64-encoded by `imaplib.IMAP4_SSL.authenticate()`.

## Token Scopes

| Service | Scope | Grants |
|---------|-------|--------|
| Mail (IMAP) | `mail:imap_ro` | Read-only IMAP access |
| Disk | `cloud_api:disk.read` | Read-only access to Yandex Disk |

## Token Lifecycle

- Tokens are valid for ~1 year
- No refresh token mechanism — re-run `python3 <full-path-to-yandex-skills>/scripts/oauth_setup.py ...` from the agent workspace CWD to get a new token
- Token file format: `{"email": "user@yandex.ru", "token.mail": "y0_..."}`

## Yandex IMAP Specifics

- Server: `imap.yandex.com`
- Port: `993` (TLS)
- Supports `SEARCH`, `FETCH`, `UID` commands
- UIDs are stable and monotonically increasing per mailbox
- Rate limits: not publicly documented, but aggressive polling (< 1 min) may trigger blocks

## References

- App registration: https://yandex.ru/dev/id/doc/ru/register-api
- Create API key: https://oauth.yandex.ru/client/new/api
- IMAP client setup: https://yandex.ru/support/mail/mail-clients/others.html
