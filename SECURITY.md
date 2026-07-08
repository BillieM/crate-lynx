# Security Policy

Crate Lynx is a personal/LAN-first application for a trusted operator. It is
published as source code, not as a hardened hosted service. Do not expose the
API, Postgres, Redis, slskd webhook, or mounted media paths directly to the
public internet.

## Supported Version

Security fixes target the current `main` branch.

## Reporting

Use GitHub private vulnerability reporting if it is enabled for the repository.
If not, open an issue with reproduction steps but do not include live secrets,
tokens, cookies, private library paths, or private media metadata.

If a local deployment secret is exposed, rotate it immediately. Important
values include `TOKEN_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `SLSKD_API_KEY`,
and `SLSKD_WEBHOOK_TOKEN`.
