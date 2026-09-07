# App-keyed token storage

Source: operator explicitly requested app-name-number keys, access_token field, unchanged email/client_id/good_at metadata; GitMark at shared skill root, ignored in Git, used for documentation discovery.

AC1: stored keys are catalog app_id plus numeric suffix, never bearer tokens.
AC2: migration preserves all tokens and metadata; duplicate import retains key; unknown catalog mapping fails without modifying source.
AC3: import, selection and health updates use source_key independently of access_token.
AC4: regression passes without live user credentials.
AC5: GitMark index exists at shared root and is ignored; documentation search uses GitMark.

No UUID, array, health schema or file relocation changes.
