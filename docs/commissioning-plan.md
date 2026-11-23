# Hosting approval and pilot decision

## Proposed infrastructure

Select DigitalOcean Basic in Frankfurt (FRA1), with Ubuntu 24.04, Caddy and one Uvicorn worker backed by durable local SQLite. The single host is a failure domain. Review Nigerian carrier latency, regional capacity and data-handling commitments before purchase. Keep encrypted application backups in Amsterdam (AMS3), and use Amazon SES in Frankfurt for approved account mail. The product owner must record the applicable Nigerian cross-border data requirements, provider terms, retention and permitted access before any personal data enters this design. [DigitalOcean regional availability](https://docs.digitalocean.com/platform/regional-availability/) · [AWS SES regions](https://docs.aws.amazon.com/general/latest/gr/ses.html)

| Budget item | Listed monthly basis checked 23 November 2026 |
| --- | --- |
| Basic 1 vCPU, 2 GiB RAM, 50 GiB SSD | $12.00. [Droplet pricing](https://www.digitalocean.com/pricing/droplets) |
| Weekly host-image backup | $2.40, calculated at 20% of the Droplet price. [Backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/) |
| Private Spaces Standard backup bucket | $5.00 base. [Spaces pricing](https://docs.digitalocean.com/products/spaces/details/pricing/) |
| SES Essentials outbound | $0.16 per 1,000 recipients at the first tier. Allow $0.16 for up to 1,000 recipients before data fees. [SES pricing](https://aws.amazon.com/ses/pricing/) |

The fixed baseline is **US$19.40/month**. Allow for domain renewal, monitoring, mail data, tax and exchange rates. Confirm regional checkout and any extras with the owner before purchase. Proposed spending ceiling is US$30 equivalent per month subject to explicit approval. Set billing alerts at US$20 and US$25 where supported, review currency and usage weekly, disable optional expansion, and stop new spending at the ceiling. Billing alerts may arrive after charges accrue.

## Commissioning sequence

1. The infrastructure custodian validates a synthetic host against the release manifest, records package versions, and restricts SSH to named administrators using keys. Bind Uvicorn to loopback and trust only the local Caddy proxy. Expose 80 for certificate validation and HTTPS redirects, and 443 for TLS. Verify DNS, public certificate renewal, CSP and headers, blocked direct backend access and forwarded-header behavior from outside. Restrict private database, spool, config and backups to the assigned individual service accounts and admin group. Keep SMTP, object storage and backup keys outside Git.
2. Configure the verified sending domain, SPF, DKIM, DMARC and bounce routing. Configure SES implicit TLS on `email-smtp.eu-central-1.amazonaws.com:2465` with region-specific scoped credentials. DigitalOcean blocks 25, 465 and 587 by default. Confirm 2465 egress and certificate validation on the approved host. Exercise delivery failure, invite/reset, expired/used links and session revocation with approved synthetic recipients. Require owner approval for any later production SMTP access or actual recipient. [DigitalOcean SMTP policy](https://docs.digitalocean.com/support/why-is-smtp-blocked/) · [SES TLS documentation](https://docs.aws.amazon.com/ses/latest/dg/security-protocols.html)
3. Use an external HTTPS uptime monitor with a two-minute cadence. Page the on-duty infrastructure custodian and pilot supervisor after two consecutive probe failures, on the first genuine operational failed write, for the first unresolved attempt exceeding 15 minutes during the supervised window, on delivery failures affecting account recovery, and if no verified off-host backup exists within 24 hours. Label expected financial-rule rejections separately. Confirm receipt of a synthetic test alert and define an escalation to the product owner after 15 minutes without acknowledgment. Logs carry safe operational fields without raw reset links, credentials or transaction descriptions.
4. Schedule the verified SQLite backup at 02:00 Lagos time. Encrypt the database and manifest client-side using authenticated public-key encryption before upload to the private Amsterdam bucket. Use a restricted backup upload key, separate restore read access and separately held decryption key. Keep daily backups for 30 days and expire them through the storage policy after validation. Test encryption, actual off-host retrieval and recovery into a fresh isolated host. Verify checksums, customer balances, references, account lifecycle audit, recovery and operator audit. Establish RPO **≤24 hours** and RTO **≤2 hours**, including decryption, service restart and reconciliation. Host images support infrastructure recovery. [Backup, restore and incident procedures](pilot-operations.md) · [Release rollback](release-candidate.md)

## Proposed named responsibilities and approvals

| Role | Assignment before commissioning |
| --- | --- |
| Product owner | Agbaji Alexander is the proposed owner, pending confirmation. Approves the budget, hosting, data handling, communications, pilot start and any restore-based rollback. |
| Infrastructure and backup custodian | Owner must enter a named primary and alternate and verify secret access, deployment, monitoring, restores and billing. |
| Pilot supervisor and recovery operator | Owner must name the supervisor and assign the separately authorized recovery operator. Supervisor may stop activity immediately. Operator records investigation and evidence through the audited workflow. |
| Independent technical reviewer | Owner must name a reviewer who verifies the PR and release gate, restore evidence and operational sign-off. |

Record names, escalation contacts, support hours and explicit approval before provisioning. Limit activities to the supervised support window.

## Go/no-go

| Check | State |
| --- | --- |
| Merged candidate and release gate | Verified on GitHub and in a clean local checkout. [Release manifest](commissioning-manifest.md) |
| Ledger, receipts, account recovery, synthetic interrupted writes, local TLS and restore | Automated integration evidence and emulated screen captures available. [Acceptance package](commissioning-acceptance.md) |
| Interactive owner walkthrough and independent technical review | Pending reviewer decisions. |
| Physical low-cost Android, TalkBack, mobile carrier, device restart and printer | Pending physical exercise and signed evidence. |
| Public TLS, approved SMTP, external alert routing, provider access, encrypted off-host restore and local latency | Require infrastructure approval and later host verification. |
| Required independent review in GitHub | Owner action pending. Required `release-gate` is already active. |
| Real onboarding | **NO-GO.** All critical checks and approvals above must pass before explicitly authorizing real onboarding. |

Proposed pilot is **three shops, at most six designated traders, for 14 calendar days**. Enter only after critical gates are green, all roles and support coverage are assigned, a previous release and backup are available, and physical checks demonstrate that transaction uncertainty is handled safely. Success means zero duplicate financial effects or cross-business disclosures, daily reconciliation with zero kobo discrepancy, at least 90% first-attempt completion across at least 20 observed ordinary workflows, all uncertain attempts investigated within 15 minutes during supervision with an auditable disposition or explicit hold, and a verified backup drill meeting RPO/RTO.

Pause writes and invitations immediately on any duplicate effect, incorrect balance, unauthorized access, unsafe retry, suspected data loss, broken certificate or account recovery, material monitoring failure, or exceeded backup freshness objective. Preserve references, logs and a verified database copy. The supervisor may pause and escalate. The product owner authorizes rollback after operator reconciliation and technical review. Preserve post-snapshot financial activity in the incident assessment, and require verified reconciliation and explicit approval before resuming.
