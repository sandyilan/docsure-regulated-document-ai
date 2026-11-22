# DocSure Security Notes

## Scope

DocSure is a local portfolio demo and uses synthetic data. It is not a certified compliance system and must not be used for real protected, health, financial, or customer data without a full security review.

## Controls demonstrated

- **Tenant scoping:** database reads use the active user's `tenant_id`.
- **Role boundaries:** only reviewer/admin roles can view the review queue, save review decisions, and view audit logs.
- **Review threshold:** extraction below 85% requires human review.
- **Source warning rule:** source text that says “pending verification” cannot be automatically accepted because of model output.
- **Audit events:** upload, extraction, and review decisions are recorded with timestamps and actor IDs.
- **Upload restrictions:** the MVP accepts PDF/TXT files and limits size to 5 MB.
- **Local model:** Ollama runs locally by default; no cloud model key is required.

## Production requirements not implemented

- SSO/OIDC identity verification and token validation.
- Server-enforced RBAC and granular permissions.
- Encryption at rest and in transit.
- Secure secret manager, key rotation, and environment separation.
- Malware scanning and document content-disarm checks.
- Durable immutable audit store and retention policy.
- Data classification, consent handling, retention/deletion workflow, and legal review.
- Vulnerability management, penetration testing, monitoring, and incident response.

## Secret-handling rule

Never commit `.env`, API keys, database passwords, or `.streamlit/secrets.toml`. The `.gitignore` file excludes local secrets.
