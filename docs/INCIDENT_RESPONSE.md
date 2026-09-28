# Incident Response (minimal)

Every section below follows the same order: **detect → contain → revoke → rotate → investigate →
recover → document**.
- Rotation procedures: [SECURITY_P2_5.md §15](SECURITY_P2_5.md).
- Signals: [SECURITY_P2_5.md §19](SECURITY_P2_5.md).
- Assign an owner and a backup before launch.

**General rules:**
- Preserve logs before changing anything: export the platform logs for the time window.
- Never paste secrets, tokens, signed URLs or document content into tickets or chat.
- Users are anonymous, so there is no one to email. If user data may have been exposed, say so on
  the site and follow the applicable breach-notification law, with advice.
- Afterwards, write a short record: timeline, cause, what was exposed, what changed. Add a
  regression test if code was at fault.

## Credential compromise (database, storage, `APP_SECRET`, proxy secret, deploy tokens)
1. **Detect.** Any of:
   - the secret shows up in a commit (gitleaks), a log, or a third-party alert;
   - the provider's audit logs show unexpected access.
2. **Contain and revoke.**
   - Revoke the credential at the provider immediately.
   - For a database role, run `ALTER ROLE … NOLOGIN`.
   - For `APP_SECRET`, rotating it ends every session.
3. **Rotate.** Issue the replacement and redeploy every service that uses it (SECURITY_P2_5 §15).
4. **Investigate.** Read the provider access logs (R2, database, platform) for the exposure window:
   look for reads, deletes, and new roles or tokens.
5. **Recover.** If data was altered, restore from point-in-time recovery (PITR) to a new instance
   and compare.
6. **Document.**

## Data exposure (one user's data visible to another)
1. **Detect.** Any of:
   - anomalies in `authorization_denied` events;
   - a user report;
   - a failing authorization test.
2. **Contain.**
   - Disable the affected endpoint with a revert or a feature cut.
   - If the scope is unclear, scale the API to zero (maintenance).
3. **Revoke.** Revoke all sessions by rotating `APP_SECRET`, if tokens may be involved.
4. **Investigate.**
   - Audit events and request logs identify which sessions requested which ids.
   - Determine the affected documents.
5. **Recover.** Fix it with a regression test first, then redeploy.
6. **Document.** Include the notification decision.

## Storage exposure (bucket public, listing enabled, token leaked)
1. **Contain.** Make the bucket private and disable public or dev URLs. Revoke the token.
2. **Investigate.** Check R2 access logs and analytics for GETs and LISTs made without our
   signature during the window.
3. **Recover.**
   - Rotate the tokens.
   - Consider deleting the exposed documents: the workspaces are temporary, and users can upload
     again.
   - Run `python -m app.reconcile`.
4. **Document.**

## Database compromise
1. **Contain.**
   - Revoke the compromised role.
   - Restrict network access to the database with the provider's IP allowlist.
   - Rotate `APP_SECRET`.
2. **Investigate.** Use the provider logs and `pg_stat_statements` to look for:
   - new roles;
   - altered tables;
   - bulk `SELECT`s.
3. **Recover.** Restore PITR from before the compromise to a new instance, then:
   - re-apply `db_roles.sql` with new passwords;
   - reconcile against storage;
   - switch over.
4. **Document.**

## Malicious PDF exploitation (`parser output refused`, crash loops, unexpected processes)
1. **Detect.** Any of:
   - a `parser output refused` log;
   - a spike in `processing_failed` from one session or IP;
   - worker CPU or memory anomalies;
   - unexpected outbound connections from the worker.
2. **Contain.**
   - Scale the worker to zero: uploads still queue, but nothing is parsed.
   - Keep the PDF only in quarantined, access-controlled storage for analysis. Never open it on a
     workstation.
3. **Revoke and rotate.** Rotate the worker's database role and storage token. The parser holds
   neither, but assume the worker host is compromised until shown otherwise.
4. **Investigate.**
   - Check PyMuPDF/MuPDF advisories for the version in `uv.lock`, and upgrade.
   - Enforce `PROCESSING_NETWORK_ISOLATION=required` where the host allows it.
5. **Recover.** Redeploy the worker from a clean build, and re-queue jobs only after the fix.
6. **Document.**

## Service abuse (floods of sessions, uploads, exports; queue saturation)
1. **Detect.** Any of:
   - rate-limit and quota events concentrated on a few IPs;
   - the queue at `QUOTA_MAX_QUEUED_JOBS`.
2. **Contain.**
   - Lower the `RATE_LIMIT_*_IP` / `QUOTA_*` limits in the environment and redeploy.
   - Block abusive IPs or ASNs at Vercel or Cloudflare.
3. **Investigate.** If a limit was bypassed, that's a bug: fix it and add a test.
4. **Recover.** Restore normal limits once traffic subsides. The sweep and retention remove what
   the abuse created.
5. **Document.**

## Mass unauthorized access (many sessions probing many ids)
1. **Detect.** Many `authorization_denied` events across sessions from related IPs.
2. **Contain.** Block the IPs at the edge and lower `RATE_LIMIT_SESSIONS*`.
3. **Investigate.** Confirm every probe was denied (404/403 in the request logs). If any
   succeeded, handle it as **data exposure** above.
4. **Recover.** Nothing to do if every probe was denied.
5. **Document.**
