# Yandex Protocol Command Coverage

This note records only command-level coverage found in official Yandex
documentation for protocol-based Calendar and Contacts services. It is separate
from RFC coverage and live probe coverage.

## Calendar / CalDAV

Official Yandex sources checked:

- `https://yandex.ru/support/yandex-360/business/admin/ru/security-service-applications`
- `https://yandex.ru/support/yandex-360/business/admin/en/security-service-applications`
- `https://yandex.ru/support/yandex-360/business/calendar/ru/sync/sync-mobile`
- `https://yandex.ru/support/yandex-360/business/calendar/ru/plug-in`

Yandex-published command coverage:

| Command | Yandex-published coverage | Matrix implication |
| --- | --- | --- |
| `PUT` | Explicit curl examples create a single event and a recurring event at `https://caldav.yandex.ru/calendars/<user_email>/events-default/<event_uid>.ics`; the same Yandex text says this `PUT` creates or changes a Calendar event. | `calendar.caldav.event.put` is directly covered by Yandex docs. |
| `GET` | Explicit curl examples read the same event `.ics` resource after creation. | `calendar.caldav.event.get` is directly covered by Yandex docs. |
| Calendar delete via CalDAV client library | Official service-application docs show Python `caldav` code that finds and deletes a calendar. The page does not print the underlying HTTP command. | Calendar deletion is Yandex-documented at library/action level only, not as an explicit HTTP command row. |

Yandex docs also name CalDAV service configuration:

- `https://caldav.yandex.ru`
- account URL `https://caldav.yandex.ru/principals/users/<login@domain>/`
- Yandex Connector works over CalDAV and CardDAV

Yandex-official command coverage not found:

- no official Yandex page found with a complete CalDAV command catalog
- no official Yandex page found with explicit `PROPFIND`
- no official Yandex page found with explicit `REPORT`
- no official Yandex page found with explicit event-resource `DELETE`

Therefore these Calendar rows are protocol-spec and live-probe rows, not
Yandex-command-documented rows:

- `calendar.caldav.principal`
- `calendar.caldav.calendars`
- `calendar.caldav.report.date_search`
- `calendar.caldav.event.delete`

Live verification on 2026-04-20:

| Method | Public | `calendar:all` | Evidence |
| --- | --- | --- | --- |
| `calendar.caldav.principal` | 401, does not work | 207, works | `capabilities/raw/calendar-probe.json` |
| `calendar.caldav.calendars` | 401, does not work | 207, works | `capabilities/raw/calendar-probe.json` |
| `calendar.caldav.report.date_search` | 401, does not work | 207, works | `capabilities/raw/calendar-probe.json` |
| `calendar.caldav.event.delete` | 401, does not work | 204, works | `capabilities/raw/calendar-probe.json` |

Conclusion: these Calendar commands are implemented by the live Yandex CalDAV
service even where the command itself is not printed in official Yandex docs.
The generated `method-scope-map.json` maps each row to
`one_of: ["calendar:all"]`.

## Contacts / CardDAV

Official Yandex sources checked:

- `https://yandex.ru/support/yandex-360/customers/mail/ru/web/abook`
- `https://yandex.ru/support/yandex-360/business/calendar/ru/plug-in`

Yandex-published command coverage:

| Command | Yandex-published coverage | Matrix implication |
| --- | --- | --- |
| none found | Yandex docs state that contacts are synchronized with CardDAV and give `carddav.yandex.ru`, username, password, and port settings. They describe creating a contact on a device and seeing it sync to Yandex Mail contacts, but do not print HTTP/CardDAV commands. | No Contacts row is directly covered by a Yandex-published protocol command. |

Yandex docs also name CardDAV service configuration:

- `carddav.yandex.ru`
- ports `443` or `8443`
- Yandex Connector works over CalDAV and CardDAV

Yandex-official command coverage not found:

- no official Yandex page found with a complete CardDAV command catalog
- no official Yandex page found with explicit `PROPFIND`
- no official Yandex page found with explicit `REPORT`
- no official Yandex page found with explicit vCard `PUT`
- no official Yandex page found with explicit vCard `GET`
- no official Yandex page found with explicit vCard `DELETE`

Therefore all current Contacts rows are protocol-spec and live-probe rows, not
Yandex-command-documented rows:

- `contacts.carddav.principal`
- `contacts.carddav.addressbook.propfind`
- `contacts.carddav.vcard.put`
- `contacts.carddav.vcard.get`
- `contacts.carddav.vcard.delete`

Live verification on 2026-04-20:

| Method | Public | `addressbook:all` | Evidence |
| --- | --- | --- | --- |
| `contacts.carddav.principal` | 401, does not work | 207, works | `capabilities/raw/contacts-probe.json` |
| `contacts.carddav.addressbook.propfind` | 401, does not work | 207, works | `capabilities/raw/contacts-probe.json` |
| `contacts.carddav.vcard.put` | 401, does not work | 201, works | `capabilities/raw/contacts-probe.json` |
| `contacts.carddav.vcard.get` | 401, does not work | 200, works | `capabilities/raw/contacts-probe.json` |
| `contacts.carddav.vcard.delete` | 401, does not work | 204, works | `capabilities/raw/contacts-probe.json` |

Conclusion: these Contacts commands are implemented by the live Yandex CardDAV
service even though official Yandex docs only describe CardDAV sync and do not
print command examples. The generated `method-scope-map.json` maps each row to
`one_of: ["addressbook:all"]`.
