# Releasing yandex-office

`yandex-office` uses dated skill versions in `YYYY.MM.DD` format.

Release policy:

- one public release version per calendar day
- if multiple changes land on the same day, batch them into the same dated release instead of inventing suffixes
- keep the current released version in `VERSION`
- keep cumulative downloader-facing release notes in `CHANGELOG.md`
- publish the same dated notes in the GitHub Release body when cutting a tag

Release checklist:

1. Merge the verified PR to `main`.
2. Update `VERSION`.
3. Append the new dated section to `CHANGELOG.md`.
4. Update any relevant `metadata.version` headers in skill markdown files.
5. Commit the release metadata update.
6. Tag the repo with `yandex-office/YYYY.MM.DD`.
7. Publish a GitHub Release from that tag using the matching changelog section.
