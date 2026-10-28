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
| Brute force/DoS | Not fully implemented | API gateway rate limits, per-account/IP limits, WAF |
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
- [ ] Centralized rate limiting.
- [ ] Production key management and key rotation.
- [ ] Automated dependency/image scanning and secret scanning.
- [ ] Encryption-at-rest configuration verified for deployment.
- [ ] Compliance review and retention schedule approved.

This is an assignment/demo baseline, not a certification of regulatory compliance or production readiness.


Payment-specific controls in this demo: the fee is server-configured, payment-intent creation is idempotent, one active payment record is permitted per consultation, patients can only see their own records, and manual reconciliation is admin-only, transition-checked and audited. Real gateway credentials, signed webhook verification, settlement/refund execution and reconciliation against provider statements remain unimplemented.
