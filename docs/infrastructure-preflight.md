# KLD-006C3 infrastructure preflight

Everything in this document uses synthetic records. The production-facing checks require explicit spending, provider, DNS and host approval. Keep the service unavailable to traders until the independent reviewer and product owner sign off.

## Checks to run now

Run from the repository root with the pinned environment, Node and Chromium. For the local HTTPS test, install the verified Caddy binary and set `KUDILEDGER_CADDY` to its path. The browser fixture uses a temporary local CA and synthetic database.

```bash
KUDILEDGER_SITE=https://localhost:9443 KUDILEDGER_HTTP_PORT=9080 \
  caddy validate --config deploy/staging/Caddyfile --adapter caddyfile
bash scripts/check_staging_units.sh
python -m unittest -v tests.test_staging_preflight
KUDILEDGER_REQUIRE_STAGING_BROWSER=1 python -m unittest discover -v
```

The systemd check runs under Linux or Ubuntu WSL and builds a disposable root containing the tracked units. The HTTPS fixture exercises both normal traffic and conflicting proxy headers against Caddy and FastAPI. On the eventual host, use the commands below to check the installed configuration and externally visible behavior.

## Approved-host checks

1. Replace the example origin with the approved staging hostname. Record the host release SHA, image, service owners, installed units and operator. Keep the app service read-only except for its state directory. Use root ownership and mode 0600 for `/etc/kudiledger/staging.env`, service ownership and mode 0700 for database, capture and staging backup directories, and service ownership and mode 0600 for the database and SMTP password file. Verify parent-directory traversal and ACLs with `namei -l` and `getfacl` locally. Inspect SQLite sidecars as well. The checker accepts the simple unquoted `KEY=value` assignments used by the example; put credentials in private files.
2. On the approved VM, run the host-file check as root from the reviewed, admin-owned release checkout. On an independent network, run the edge check with a current system CA trust store. These checks read private file metadata and fixed HTTPS/HTTP routes. They do not emit environment values, HTTP bodies or TLS error details. Keep test output and screenshots of sensitive host state private.

```bash
# On the approved VM, after the first synthetic DB has been created.
origin='https://staging.example.test' # Replace with the approved origin.
sudo /opt/kudiledger/venv/bin/python -m scripts.staging_preflight \
  "$origin" --env-file /etc/kudiledger/staging.env

# From a separate approved network, set origin to the same approved value.
python -m scripts.staging_preflight "$origin" --edge
```

3. Inspect startup arguments with `systemctl show kudiledger-staging -p User -p Group -p ExecStart -p EnvironmentFiles -p UMask`. Confirm the installed command matches the checked-in `127.0.0.1:8000` listener, one worker and explicit loopback-only proxy trust. Check `ss -ltnp` for IPv4 and IPv6 listener scope, and verify port 8000 is unreachable from an approved independent network. Confirm direct local plaintext gets HTTP 400 with `curl --silent --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:8000/app`. Only Caddy should provide the public web endpoint. Verify the external check rejects a wrong HTTP redirect and accepts HTTPS despite a conflicting client scheme header. The separately tested local fixture verifies client address spoofing is stripped before rate limiting. Confirm renewals and alerting against the actual domain after approval.
4. Check `systemctl list-timers` for backup at 02:00 Africa/Lagos and monitoring every two minutes. Confirm that neither `systemctl` output nor log excerpts shared for review contains secrets or account links. Run the synthetic restore drill and external alert-routing drill before go-live.

## Encrypted off-host backup and restore

- Stage a consistent, verified SQLite backup and SHA-256 manifest using the existing backup timer. These include committed financial records, account lifecycle events and recovery and operator audit. Keep the private spool at `/var/backups/kudiledger` and allow the app service no access.
- Use a separate backup job identity and pinned `age` to encrypt the snapshot plus manifest together with an authenticated-encryption envelope. Verify the recovery public key fingerprint during commissioning. Give the encryption job read-only access to a handoff copy in a private spool outside the app's writable paths. Keep the private key offline with the recovery custodian and a sealed alternate. Capture encrypted object hashes independently. Never transmit or retain plaintext off-host.
- Pull the ciphertext daily from an independent custodian-controlled machine with a restricted read-only transfer identity limited to the encrypted spool. This machine holds the backup bucket's scoped Read/Write/Delete key, separate from site, SMTP and restore identities. DigitalOcean Spaces' native limited write key can also delete objects. Keep that key off the application VM entirely. Use unique object keys, bucket versioning and admin-controlled retention where verified, and retain an independent protected copy to cover uploader credential compromise. Confirm private access, no CDN/public policy, expected versioning and support for recovery from accidental deletion on the actual account. [Spaces access controls](https://docs.digitalocean.com/products/spaces/how-to/manage-access/)
- Use a separate read-only restore key. On a fresh isolated machine, fetch one object, verify its recorded ciphertext hash, decrypt with the offline key and verify the snapshot manifest before restoring via the documented SQLite process. Reconcile balances to the kobo, transaction references, recovery states and account and operator audits. Prove restored sessions cannot be reused. Revoke temporary access and securely dispose of decrypted drill files. Maintain **RPO ≤24 hours** and **RTO ≤2 hours**. Record timings from actual off-host retrieval through reconciliation. Retain daily copies for 30 days after the owner approves retention. [Existing restore and incident procedures](pilot-operations.md)

## SMTP, monitoring and escalation

Use the approved SES Frankfurt sender identity, domain verification, DKIM, SPF/MAIL FROM and DMARC alignment, with implicit TLS on port 2465. Verify the provider's DNS records only after approval. Test the TLS handshake first with no mail send. Keep capture mode until sandbox recipients and sender credentials are approved. Check SES bounces and delivery failure alerts, reset token validity after delivery failure, and authorized synthetic end-to-end delivery as separate checkpoints. [SES endpoint](https://docs.aws.amazon.com/general/latest/gr/ses.html) · [TLS wrapper](https://docs.aws.amazon.com/ses/latest/dg/security-protocols.html) · [Sender identity](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)

Use an independent two-minute HTTPS monitor and route two consecutive failed probes to the on-duty infrastructure custodian and supervisor. Send the same alert for the first operational failed write, recovery attempts unresolved after 15 supervised minutes, mail failures affecting recovery or a missing verified off-host copy at 24 hours. Review expected validation rejections separately from failed writes. Verify both recipients receive synthetic test alerts and route to the product owner after 15 minutes without acknowledgment. Keep contact data in a private on-call roster.

| Responsibility | Approval gate |
| --- | --- |
| Product owner | Confirm named owner and contact, approve provider, domain, budget and pilot start, authorize rollback. |
| Infrastructure and monitoring custodian | Enter primary/alternate name, paging channel and fallback phone. Own TLS, runtime, alerts and cost review. |
| Independent backup and recovery custodian | Enter primary/alternate and contact. Hold recovery key under dual custody with named alternate, attest restore and retention. |
| Pilot supervisor and restricted recovery operator | Enter named primary/alternate and incident route. Supervisor can pause immediately. Operator preserves evidence, classifies uncertainty and records audited decisions. |
| Technical reviewer | Record named reviewer, review link, approval decision and evidence. |

Stop on duplicate financial effects, incorrect balances, data loss, isolation failure, unsafe retry, broken TLS or auth, loss of monitoring, or missed backup freshness. Pause writes and invitations, retain evidence and a verified snapshot, escalate, then reconcile before the owner authorizes rollback or restart.

The [proposed cost model](commissioning-plan.md) is **US$19.40/month** for the base VM, weekly host image and Spaces. Domain, mail, monitoring, separate transfer runner, taxes and exchange rates can add cost. Treat US$30 as a proposed budget ceiling requiring approval and reconfirm the final checkout. [Droplet pricing](https://www.digitalocean.com/pricing/droplets) · [Backups](https://docs.digitalocean.com/products/backups/details/pricing/) · [Spaces](https://docs.digitalocean.com/products/spaces/details/pricing/)
