# Yandex Onboarding Notes

This file is optional operator guidance.

Authoritative onboarding instructions live in `SKILL.md`.
If `SKILL.md` and this file disagree, follow `SKILL.md` and then fix this file.

## Purpose

Use this file only for:

- mailbox UI prerequisites
- token revocation link
- short troubleshooting notes

Do not duplicate the onboarding contract here.

## Token Revocation

- EN: `https://id.yandex.ru/personal/data-access`
- RU: `https://id.yandex.ru/personal/data-access`

## Troubleshooting

- `AUTHENTICATE failed`: wrong token, wrong mailbox, or IMAP/OAuth is disabled in mailbox settings.
- No fetched mail: sender filter is too strict, or there is no matching mail yet.
- Wrong data path: onboarding was not run from the agent workspace CWD.

## Maintainer Note

Keep this file short.
Do not turn it into a second onboarding spec.
