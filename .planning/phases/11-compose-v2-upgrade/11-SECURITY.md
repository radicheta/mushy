---
phase: 11
slug: compose-v2-upgrade
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-13
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| host tooling | apt package install from standard Ubuntu repo | Package binary — signed by Ubuntu archive key |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-11-01 | Tampering | apt package source | accept | Package from Ubuntu jammy-updates (standard signed repo). No third-party PPA or manual binary download. Existing apt GPG verification applies. | closed |
| T-11-02 | Denial of Service | brief downtime during container recreation | accept | ~30s downtime during `docker compose down` / `up -d` is expected and accepted. No new attack surface. Elder-plops is on a private LAN behind pfSense. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

**Note:** No new network endpoints, authentication surfaces, or data processing paths introduced. All existing security controls preserved:
- TimescaleDB bound to 127.0.0.1:5432 (not exposed to LAN)
- Bridge uses host networking with CycloneDDS over Tailscale
- TIMESCALE_PASSWORD sourced from .env (gitignored)

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T-11-01 | apt package from official Ubuntu repo; GPG-signed; no elevated risk vs any other system package | plan author | 2026-04-13 |
| AR-11-02 | T-11-02 | ~30s downtime is acceptable for infrastructure upgrade on private LAN; no SLA violated | plan author | 2026-04-13 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-13 | 2 | 2 | 0 | gsd:secure-phase orchestrator |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-13
