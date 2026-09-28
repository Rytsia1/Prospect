# Prospect — Legal & Trust Human Review Checklist

This checklist centralizes all unresolved legal, organizational, and operational items identified during the **L1 Legal & Trust Baseline** implementation. In accordance with Prospect engineering and legal rules, **no legal facts, entity names, contacts, or retention durations have been fabricated or assumed.**

Every item marked below with `[ ]` requires explicit human review and input by the platform operator and qualified legal counsel prior to commercial launch or public production release.

---

## 1. Operator & Organizational Identity

- [ ] **Operator Legal Name:** Define the exact legal entity or individual operating the Prospect platform (e.g., registered corporate entity name or individual proprietor).  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — OPERATOR LEGAL NAME]`
- [ ] **Operator Physical Address:** Provide the registered business address or physical location for legal service of process and official correspondence.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — OPERATOR PHYSICAL ADDRESS]`
- [ ] **Commercial Status & Form:** Determine whether Prospect is operating as an open-source research demonstration, a non-profit tool, an early-stage startup, or a commercial enterprise.

---

## 2. Official Contact Mechanisms

- [ ] **Privacy Inquiries & Data Rights Contact:** Establish and publish a dedicated contact address for privacy-related inquiries and data subject requests.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — PRIVACY CONTACT EMAIL / FORM]`
- [ ] **Security & Responsible Disclosure Contact:** Establish a monitored contact channel (e.g., `security@...` or a vulnerability reporting portal) for security researchers.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — SECURITY CONTACT EMAIL]`
- [ ] **Copyright & Takedown Agent Contact:** Designate an official copyright contact/agent to receive DMCA or equivalent intellectual property infringement notices.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — COPYRIGHT CONTACT EMAIL]`
- [ ] **General Support & Abuse Reporting:** Designate general user support and acceptable-use violation reporting channels.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — SUPPORT / ABUSE CONTACT]`

---

## 3. Data Retention & Backups Policy

- [ ] **Document Retention Duration Confirmation:** Confirm whether the technical default of 30 days (`DOCUMENT_RETENTION_DAYS = 30`) aligns with user expectations, storage economics, and legal obligations.  
  *Current status in legal pages:* Technical default of 30 days disclosed; formal policy flagged for human confirmation.
- [ ] **Anonymous Workspace Grace Period Confirmation:** Confirm whether 24 hours of inactivity (`WORKSPACE_GRACE_HOURS = 24`) following session expiration is the desired window before total workspace purging.
- [ ] **Failed Upload Retention Confirmation:** Confirm whether 24 hours (`FAILED_DOCUMENT_RETENTION_HOURS = 24`) is appropriate for purging failed upload metadata.
- [ ] **Production Database Backup Retention:** Establish provider-managed Point-In-Time Recovery (PITR) retention policy (recommended: $\le$ `DOCUMENT_RETENTION_DAYS + 7` days, i.e., $\le 37$ days).  
  *Current status:* Backups are not yet configured in production infrastructure (`docs/SECURITY_P2_5.md §16`).
- [ ] **Disaster Recovery & Restore Testing:** Schedule and perform the first quarterly database restore rehearsal before production launch.

---

## 4. Hosting, Infrastructure & Data Residency

- [ ] **Production Cloud Providers Confirmation:** Confirm the final contracted infrastructure providers:
  - Frontend: Vercel
  - Backend API: Railway / Render
  - Worker: Railway / Render
  - Relational Database: Managed PostgreSQL (Railway / Supabase)
  - Object Storage: Cloudflare R2 / Supabase Storage
- [ ] **Data Center Locations & Cross-Border Data Transfers:** Document the exact geographic locations/regions where databases and object storage buckets are provisioned.  
  *Current status in legal pages:* Identified as globally distributed; exact tenant regions flagged as `[REQUIRES VERIFICATION — HOSTING AND STORAGE REGIONS]`.
- [ ] **Subprocessor Agreement Verification:** Verify Data Processing Agreements (DPAs) or standard contractual clauses (SCCs) with Vercel, Railway/Render, Cloudflare, and PostgreSQL database hosts.

---

## 5. Legal Basis & Regulatory Assessment

- [ ] **Legal Basis Assessment:** Conduct a formal data protection assessment (e.g., under Indonesian Law No. 27/2022 on Personal Data Protection (UU PDP), EU GDPR, or other applicable privacy laws) to establish the lawful basis for processing financial documents (e.g., contractual necessity, legitimate interest, or explicit user consent).  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — LEGAL BASIS ASSESSMENT]`
- [ ] **Indonesian PSE Registration Assessment:** Determine whether the platform must register as an Electronic System Operator (Penyelenggara Sistem Elektronik / PSE) with the Ministry of Communications and Informatics (Kominfo). *(Note: Explicitly out of scope for L1 implementation, but required prior to Indonesian public launch).*
- [ ] **Financial Regulatory Boundary Review:** Confirm with legal counsel that the current disclaimer copy sufficiently establishes that Prospect is solely an informational document extraction tool and not a licensed investment adviser, broker-dealer, or financial intermediary.

---

## 6. Terms of Use, Liability & Governing Law

- [ ] **Governing Law & Jurisdiction:** Specify the governing law and designated dispute resolution forum (court jurisdiction or arbitration venue).  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — GOVERNING LAW AND JURISDICTION]`
- [ ] **Statutory Limitation of Liability:** Finalize liability caps (e.g., amount paid by user in preceding months, or nominal cap) with qualified legal counsel.  
  *Current status in legal pages:* `[REQUIRES HUMAN INPUT — FORMAL LIABILITY TERMS]`
- [ ] **Age & Eligibility Policy:** Decide whether an explicit minimum age requirement (e.g., 18+, 13+, or age of majority) applies to the platform.  
  *Current status in legal pages:* `[REQUIRES HUMAN DECISION — AGE / ELIGIBILITY POLICY]`

---

## 7. Open Source & Third-Party Licensing

- [ ] **PyMuPDF / AGPL-3.0 License Compliance Review:** PyMuPDF is licensed under GNU AGPL-3.0 (commercial licenses are available from Artifex). Public network deployment of AGPL software requires compliance with AGPL network disclosure provisions or acquiring a commercial license (`README.md §134-136`). Review with legal counsel.

---

## 8. Incident Response & Breach Notification

- [ ] **Incident Response Ownership Assignment:** Assign primary and backup incident response owners as required by `docs/INCIDENT_RESPONSE.md`.
- [ ] **Statutory Notification Timelines:** Identify any applicable statutory incident notification windows (e.g., under UU PDP or GDPR) and document internal escalation procedures.
