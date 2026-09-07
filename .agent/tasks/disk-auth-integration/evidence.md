# Disk/auth integration

Source: operator approved integration and installation in this Telegram conversation.

Integrated origin/main, adb1151 Disk CLI, and PR 65 (662ca1a). Resolved four conflicts retaining managed-only Disk runtime and canonical secret migration.

Verification: 232 tests passed, one datetime deprecation warning. Earlier test runs failed due to incorrect test runtime placement, then missing parent directory; corrected execution paths, not product guards.

Gitleaks: all 16 findings classified as OAuth client_id identifiers: 13 config catalog entries, one calendar test source, two generated calendar fixtures. No credential value is included here. No allowlist added.

Installed uncommitted mail patch preserved in installed-mail-before.patch; equivalent logic exists in integrated source.
