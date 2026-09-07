# Automatic token key migration

Source: operator requires automatic format detection and conversion; manual migration is unacceptable.

AC1: normal managed-auth loading converts bearer-keyed entries and saves them before selection.
AC2: already migrated files stay unchanged on load.
AC3: old location plus old format migrates through normal authorization.
AC4: unknown app fails or uses existing dispatcher catalog resolution, never invented names.
AC5: metadata and private atomic writes preserved, regression passes.
