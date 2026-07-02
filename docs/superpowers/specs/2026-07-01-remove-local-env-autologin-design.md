# Remove local `.env` credential auto-login

**Date:** 2026-07-01
**Status:** Approved (scope confirmed: local auto-login only; keep shared-account mode)

## Problem

When the workshop runs locally (any non-Replit process), `env_fallback_allowed()`
returns `True`, so `creds_for()` silently falls back to the `SIGNALWIRE_*` values
loaded from `.env`. Every fresh browser session is therefore pre-authenticated and
skips the credential screen ("auto-login"). This is no longer wanted: every
attendee should enter their own credentials.

## Scope

- **Remove:** the local/dev env-credential fallback (the accidental auto-login).
- **Keep:** `WORKSHOP_SHARED_ACCOUNT` shared-account deployment mode, which
  intentionally runs the build on one pre-provisioned account and scopes each
  attendee's own creds to the outbound/verify finale.

## Change

`main.py`:

1. Delete `env_fallback_allowed()` (its only job was `(not REPLIT_DEPLOYMENT) or
   shared_account_active()`).
2. In `creds_for()`, gate the env-cred fallback directly on
   `shared_account_active()` instead of `env_fallback_allowed()`.
3. Update the `creds_for()` docstring to state the fallback is shared-account only.

Net effect on the three resolvers:

| Resolver | Off shared mode (normal) | Shared mode |
|---|---|---|
| `creds_for` | session creds, else `{}` | session creds, else env creds |
| `build_creds_for` | = `creds_for` (session-only) | env creds |
| `own_creds_for` | = `creds_for` (session-only) | session creds only |

`REPLIT_DEPLOYMENT` is no longer read by application logic after this change; it
was referenced only by `env_fallback_allowed()`.

## Tests

- **New regression test:** with `SIGNALWIRE_*` env present, `WORKSHOP_SHARED_ACCOUNT`
  unset, and `REPLIT_DEPLOYMENT` unset, a fresh session's `creds_for()` returns `{}`
  (proves no local auto-login). Red before the change, green after.
- **Existing tests unaffected:** integration harnesses already set
  `REPLIT_DEPLOYMENT=1` to suppress the fallback; shared-mode tests set
  `WORKSHOP_SHARED_ACCOUNT=1`. Now-stale comments about `REPLIT_DEPLOYMENT`
  suppressing auto-login are corrected to note the fallback is shared-account-only.

## Out of scope

- The `.env` file itself (a local secret, still used for shared-mode and solo
  REST/RELAY testing) is left untouched.
- Shared-account mode, wizard UI, and credential POST/validation are unchanged.
