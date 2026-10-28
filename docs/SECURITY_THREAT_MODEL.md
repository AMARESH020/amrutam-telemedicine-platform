# Security checklist and threat model

## Assets and classification
- Identity/contact data: confidential personal data.
- Consultation and prescription content: highly sensitive health data.
- Booking metadata and audit events: confidential; access restricted.
- Secrets/signing keys: restricted; never commit to Git.

## Threats and mitigations
| Threat | Mitigation in this repository | Additional production control |
|---|---|---|
| Password theft | Argon2 password hashing; generic login errors | MFA, breached-password screening, lockout/risk detection |
| Token forgery/replay | Signed, expiring JWT; secret configured through environment | Managed signing keys, rotation, refresh/revocation strategy |
| Privilege escalation | Patient self-registration only; RBAC and ownership checks | Admin provisioning workflow and periodic access review |
| Double booking | Idempotency key, transaction, uniqueness constraints, row lock on PostgreSQL | Load test against PostgreSQL; idempotency TTL and key/request fingerprint |
| Injection | SQLAlchemy parameterized queries; Pydantic validation | SAST/DAST and security review |
| Brute force/DoS | Redis-backed IP sliding-window limit on login, token, and registration (5 requests per 60 seconds per endpoint/IP); configured Redis failure returns 503 | API gateway/WAF, per-account limits, broader DDoS protection, and alerting |
| PHI leakage | No request-body logging added | Redaction tests, access monitoring, encryption/key management |
| Insider misuse | Audit events for key changes | Append-only/central audit store, alerting, retention policy |
| Dependency compromise | CI dependency installation | Dependabot, pinned lock file, SBOM and image scanning |
| Data loss/ransomware | PostgreSQL volume for local development | Encrypted backups, PITR, restore drills, separate-account copies |

## Security acceptance checklist
- [x] Passwords hashed using Argon2.
- [x] JWT expiry and role-based authorization.
- [x] Public users cannot self-assign staff roles.
- [x] Input constraints and duplicate-email handling.
- [x] Booking idempotency and database uniqueness constraints.
- [x] Audit records for key business actions.
- [x] TOTP MFA enrollment, encrypted secret storage, recovery-code single use and TOTP replay protection tested.
- [x] Redis-backed shared IP rate limiting for login, token, and registration; live Redis integration and fail-closed behavior tested. Gateway/WAF and per-account limits remain outstanding.
- [ ] Production key management and key rotation.
- [ ] Automated dependency/image scanning and secret scanning.
- [ ] Encryption-at-rest configuration verified for deployment.
- [ ] Compliance review and retention schedule approved.

This is an assignment/demo baseline, not a certification of regulatory compliance or production readiness.


Payment-specific controls in this demo: the fee is server-configured, payment-intent creation is idempotent, one active payment record is permitted per consultation, patients can only see their own records, and manual reconciliation is admin-only, transition-checked and audited. Real gateway credentials, signed webhook verification, settlement/refund execution and reconciliation against provider statements remain unimplemented.

## Account-aware authentication cooldown

**Threat:** Distributed password guessing against a user account can evade
a purely IP-based limit by sending requests from multiple addresses.

**Implemented controls:**
- Track failed password and MFA authentication by an HMAC-derived account
  identifier, rather than putting raw email addresses in Redis keys.
- Keep failure counts for 15 minutes after the most recent failed attempt.
- Start a bounded progressive cooldown after six failed attempts, increasing
  the delay up to 30 seconds.
- Clear account failure state after successful authentication.
- Return HTTP 429 and Retry-After when a failed attempt encounters an active
  cooldown. Return HTTP 503 when the configured Redis protection is unavailable
  rather than silently bypassing it.
- Do not impose a permanent account lock; a complete valid credential sequence
  can still authenticate during a cooldown.

**Residual risks and verification limits:** account-specific rate limiting
does not replace IP-based throttling, gateway/WAF controls, MFA, alerting, or
monitoring. Since an incorrect password is verified before the cooldown check,
an attacker can still impose password-hashing work. The account-specific Redis path has fake-client unit tests and passed
a smoke test against the local Docker Redis service covering hashed keys,
progressive cooldowns, and clearing state. Multi-replica abuse handling and
production capacity have not been independently validated. The production JWT
secret must be strong and stable because it is used to derive account limiter
keys.
