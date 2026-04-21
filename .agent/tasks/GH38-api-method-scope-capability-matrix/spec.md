# GH38: API-method x scope capability matrix

Status:
- FROZEN
- phase: spec-frozen
- frozen for build after user review

This task initializes the repo-task-proof-loop work for GitHub issue #38 in
`bizyumov/yandex-office`.

## Source Context

Primary issue:
- GitHub issue #38: build an API-method x scope capability matrix for Yandex Office.

Auth design anchor:
- `references/yandex-office-auth-principles.md`

The matrix must extend that auth model instead of replacing it.

Capability process anchor:
- `capabilities/README.md`

The delivered capability map lives under `capabilities/` and is the persistent
API-method x auth-context evidence source for yandex-office.

## Existing Auth Model To Preserve

The PR32 auth principles define these core entities:

- `user`: the human owner and OAuth consent authority.
- `agent`: the OpenClaw executor acting for the user.
- `yandex-office`: the component the agent uses to perform Yandex Office work.
- `yandex account`: the verified Yandex identity, identified by email and local account name.
- `app`: the Yandex OAuth app, identified by `client_id`, configured with scopes.
- `scope`: a Yandex OAuth permission atom, identified by id.
- `token`: the OAuth credential authorized by the user, issued for a Yandex account, linked to an app, stored and used internally by `yandex-office`.
- `sub-skill`: a functional area such as `disk`, `mail`, `calendar`, `telemost`, `forms`, `tracker`, `directory`, or `contacts`.
- `asset`: user data or capability reachable through a Yandex account.

GH38 adds one missing entity:

- `api_method`: a concrete callable operation, identified by service/sub-skill, protocol, method/command, endpoint/path, and request shape.

The important relationship is:

- `sub-skill operates_on asset`
- `sub-skill calls api_method`
- `api_method is_satisfied_by scope`
- `app includes scope`
- `token linked_to app`
- `yandex-office uses token internally to call api_method`

This matrix is the evidence layer that makes `api_method is_satisfied_by scope`
explicit and experimentally grounded.

## Problem Statement

The current skill can reason about accounts, apps, tokens, and broad sub-skill
scope needs, but it cannot reliably answer authorization questions at the
method level.

Examples of questions the current model cannot answer deterministically:

- Which exact scopes are sufficient for `GET /v1/disk/resources`?
- Which exact scopes are sufficient for `POST /v3/issues/_search`?
- Which API methods become available when a user authorizes a given app?
- Which method in a multi-step workflow will fail for the current token?
- Which atomic scopes does the user need to mint so the skill can test this?

Service-level assumptions are not enough. The actual execution surface is a
graph of API methods, and each method needs empirical scope capability data.

## Design Principles

### D1. Method-level capability is the matrix unit

The matrix row is a concrete API method, not a sub-skill and not a workflow.
Sub-skills are useful functional groupings, but they are not the authorization
boundary.

### D2. Scope cells are sufficiency probes, not MECE categories

The matrix column is an OAuth scope.

A cell answers:

> Is a token containing this single scope sufficient to call this API method
> successfully under the controlled fixture?

Scopes are not mutually exclusive. Several scopes can be valid for a single
method, and that is an expected result.

### D3. Runtime API responses are final truth

The PR32 auth principles say: use runtime API responses as final truth; scopes
guide onboarding and remediation, but must not become premature runtime blockers.

GH38 follows that rule:

- documented scope expectations seed the experiment
- atomic-token probe results populate the matrix
- runtime code must treat the matrix as capability/remediation data, not as a
  reason to block calls before the API has the final say unless a later user
  decision explicitly changes that behavior

### D4. Token handling is part of the experiment

This task requires real tokens for live probing.

The first practical output must be a normalized involved-scope list so the user
can mint one atomic token per scope. "Atomic token" means a token issued through
an app/profile with one tested scope, used to determine whether that scope is
sufficient for a method.

Real tokens are in scope for the live experiment. Committed artifacts must not
contain raw token values, private emails, personal resource names, org IDs, form
IDs, issue keys, or unredacted live response bodies.

### D5. Full method inventory is required

The matrix must not stop at methods currently called by existing scripts.

For each sub-skill, retrieve and model the full relevant API method list, then
classify each method:

- `current_used`: the skill actually calls this method today.
- `implemented_unused`: code exists locally but current workflows do not use it.
- `upstream_available`: upstream API documents the method but the skill does
  not implement it yet.
- `unsupported_or_deferred`: the method is known but intentionally unsupported,
  inaccessible, deprecated, impossible to fixture safely, or outside the
  Yandex Office skill boundary.

### D6. Existing app/token model remains intact

The matrix does not make the user choose scopes directly as the normal UX.
Per PR32 principles, users choose accounts, sub-skills, and apps; Yandex Office
stores and resolves tokens internally.

The matrix backs app profile design and remediation by showing which API
methods each app's scopes are expected and verified to cover.

## Requirements

### R1. Full API method inventory

Produce a machine-readable inventory for every relevant sub-skill:

- `disk`
- `mail`
- `calendar`
- `telemost`
- `forms`
- `tracker`
- `directory`
- `contacts`
- any other Yandex Office sub-skill present in this skill tree

Each method row must include:

- stable method id
- sub-skill/service
- upstream service family
- protocol (`rest`, `imap`, `caldav`, `carddav`, or other)
- HTTP method/path or protocol command
- operation name
- request shape and required fixture fields
- response shape needed to prove success
- source locations in local code/docs
- upstream documentation source
- classification (`current_used`, `implemented_unused`, `upstream_available`,
  `unsupported_or_deferred`)
- initial expected scopes, if known

### R2. Involved scope inventory for atomic tokens

Produce the concrete list of OAuth scopes involved in the experiment.

The list must be grounded in actual Yandex scope/app data:

- `config.skill.json`
- `references/yandex-oauth-scopes.json`
- upstream OAuth/app documentation when local data is incomplete

For each scope, record:

- scope id
- service family
- human description if available
- source of truth
- app profiles currently containing it
- whether the user needs to mint/provide an atomic token for it

This list is an early deliverable because the user needs it to create/provide
the one-scope tokens used by live probes.

### R3. Controlled live probe workflow

Define and execute a repeatable live probe process:

1. User creates or provides atomic tokens for the scope list.
2. Tokens are stored only in the agreed local runtime/test auth location.
3. Probe fixtures define safe test assets and identifiers for each method.
4. Each method is tested against relevant atomic tokens.
5. Each cell records the observed result and evidence reference.
6. Raw outputs are redacted before being committed or summarized in evidence.

### R4. Matrix representation

Provide a machine-readable matrix where:

- rows reference method ids
- columns reference scope ids
- cells record observed status
- several `works` cells per row are valid and expected

Allowed cell statuses:

- `works`
- `does_not_work`
- `not_applicable`
- `not_tested`
- `unclear_needs_retest`

Each tested cell must include:

- timestamp
- method id
- scope id
- token fixture id or atomic-token label, never raw token
- request fixture id
- HTTP status or protocol-level result
- redacted evidence artifact path
- notes when needed

### R5. Runtime consumption contract

Document how runtime/auth code should consume the reviewed matrix in the
existing PR32 model:

- map requested operation to one or more `api_method` rows
- map token -> app -> scopes using verified token/app metadata
- compare app scopes with matrix-proven sufficient scopes for the method
- use the result for app profile design, onboarding validation, diagnostics,
  and permission remediation
- preserve the PR32 rule that live API responses remain the final truth

This requirement is about wiring the matrix into the auth design as a
capability/remediation layer. Any change that turns matrix lookup into a
pre-call hard blocker must be separately specified and accepted.

### R6. Evidence and validation

Keep task evidence under:

- `.agent/tasks/GH38-api-method-scope-capability-matrix/`

Required task artifacts:

- `spec.md`
- `evidence.md`
- `evidence.json`
- raw redacted artifacts under `raw/`

Validation must check at least:

- every matrix row references an existing method id
- every matrix column/cell references an existing scope id
- every status is from the allowed vocabulary
- every tested cell has an evidence reference
- no raw OAuth token-shaped strings are present in committed artifacts

## Acceptance Criteria

### AC1. Auth-model alignment

The spec and deliverables explicitly embed the PR32 auth principles:

- user is the OAuth consent authority
- agent executes delegated work
- Yandex Office stores/resolves/uses Yandex tokens internally
- apps include scopes
- tokens link accounts and apps
- sub-skills call API methods
- API methods are empirically mapped to sufficient scopes

### AC2. Full method inventory

A documented and machine-readable full API method inventory exists for every
Yandex Office sub-skill, with each method classified as `current_used`,
`implemented_unused`, `upstream_available`, or `unsupported_or_deferred`.

### AC3. Scope list for token minting

A normalized involved-scope inventory exists and clearly identifies the atomic
single-scope tokens the user must create/provide for live probing.

### AC4. Live probe process

The task includes a controlled repeatable process for running live Yandex API
probes with atomic tokens, redacting evidence, and recording method x scope
results.

### AC5. Empirical capability matrix

A machine-readable matrix exists where each tested cell records whether one
scope token was sufficient for one API method under the controlled fixture.
Multiple working scopes for the same method are supported.

### AC6. Runtime consumption guidance

Documentation explains how the matrix supports app profile design, onboarding
validation, permission diagnostics, workflow capability checks, and future API
expansion while preserving runtime API response truth.

### AC7. Secret handling

Real OAuth tokens may be used locally for probing, but committed artifacts do
not contain raw token values, private emails, org IDs, personal resource names,
or unredacted live response bodies.

## Implementation Outline

1. Read local code/docs and upstream API documentation for every sub-skill.
2. Build the full method inventory and classify each method.
3. Build the involved-scope inventory.
4. Give the user the atomic token minting list.
5. Define local token/fixture layout for live probes.
6. Run live probes with user-provided atomic tokens.
7. Persist redacted empirical matrix results.
8. Add validation for inventory, matrix, evidence, and secret hygiene.
9. Write evidence and verifier verdicts for the repo-task-proof-loop.

## Scope Notes

In scope:

- retrieving the full API method list for every sub-skill
- producing the involved OAuth scope list
- requesting user-provided atomic tokens for those scopes
- storing real tokens locally for controlled live probing
- performing live Yandex API probes
- producing the empirical API-method x scope matrix
- defining the runtime consumption contract for the existing auth design

Not in scope unless separately requested:

- replacing the PR32 auth model
- making scopes the primary end-user choice
- committing real secrets or unredacted live API data
- changing OpenClaw-wide secret storage outside `yandex-office`
