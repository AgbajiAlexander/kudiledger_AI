# KLD-006C0 staging architecture

## Hosting and monthly planning estimate

Prices checked on 23 November 2026. These are advertised starting points and exclude taxes, exchange fees, domain registration, email, and off-host backup storage unless stated.

| Option | Monthly starting point | Pilot tradeoff |
| --- | --- | --- |
| DigitalOcean Basic 2 GiB | US$12 for one VM, or US$14.40 with its 20% weekly VM backup add-on | Recommended baseline. One local SQLite volume, Caddy, systemd jobs and enough room for Python and password hashing. A provider VM snapshot complements the verified SQLite backup. |
| Hetzner Cloud CX23 in Germany | EUR 5.49 before VAT and public IPv4 under the June 2026 price schedule | Lower base price. Confirm availability, IPv4 fees, support expectations and access from Nigerian mobile networks before selection. |
| Render Starter with 1 GB persistent disk | US$7.25 for compute and disk | Managed HTTPS and less VM work. SQLite needs a paid persistent disk and a single instance. The 512 MB starter tier needs load verification and the local systemd backup design would need adapting. |
| Local rehearsal | US$0 incremental hosting | Synthetic validation with a temporary CA. Useful for review and device checks on a trusted network. |

Sources for these estimates are [DigitalOcean pricing](https://www.digitalocean.com/pricing/droplets), [DigitalOcean backup pricing](https://docs.digitalocean.com/products/backups/details/pricing/), [Hetzner Cloud price schedule](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), and [Render pricing](https://render.com/pricing) and [disk limits](https://render.com/docs/disks).

For budgeting, reserve **US$18–30 equivalent per month** for the recommended pilot while obtaining separate quotes for DNS, email and encrypted off-host storage. That range is a planning estimate. Confirm provider fees, taxes, payment method and naira conversion before approval. Test latency and reliability from the traders' actual networks and review data location and access before selecting a region. No resources were provisioned.

## Recommended layout

Public HTTPS goes to Caddy, which proxies to one unprivileged Uvicorn worker on `127.0.0.1:8000`. SQLite lives on the host's persistent local filesystem. Use one host and a small supervised cohort. Keep external access limited to the approved staging edge, with firewall rules for necessary TLS traffic and restricted administrative SSH. SQLite serializes writes and this layout has a single-host failure domain. Review lock errors, latency, backup sizes and restoration time during supervision. Plan a PostgreSQL migration before multiple writable replicas or higher availability.

The files in [deploy/staging](../deploy/staging/) are the Linux systemd and Caddy configuration. After approval, provision a patched Caddy release and Python 3.13, install the pinned requirements in `/opt/kudiledger/venv`, and place the reviewed commit under a read-only `/opt/kudiledger/current`. Create a dedicated `kudiledger` account and private data, capture and backup directories. Copy the example environment to `/etc/kudiledger/staging.env` with restrictive permissions. Set the Caddy service environment separately using a systemd drop-in, with `KUDILEDGER_SITE` set to the approved hostname and `KUDILEDGER_BIND` set to the approved interface. Caddy defaults to loopback. Open only the ports required for approved ACME issuance, redirects and HTTPS. Keep the API port private.

Use `caddy validate --config ... --adapter caddyfile`, `systemd-analyze verify` for the copied units, and explicit host approval before using systemd to start staging and timers. Use a valid publicly trusted certificate on an approved hostname. Caddy replaces inbound forwarding headers and the API trusts only its loopback peer. Keep untrusted workloads off the host. The loopback checks used Caddy 2.11.9 and a temporary local CA. Run the TLS test again on the selected environment. The local CA is for loopback rehearsal only.

Store the database, capture, SMTP credential file and backups outside Git. Default capture mode delivers only to `.test` addresses and writes to a private local directory. An approved real pilot may set `KUDILEDGER_MAIL_MODE=smtp`, with trusted `KUDILEDGER_PUBLIC_ORIGIN`, `KUDILEDGER_SMTP_HOST`, `KUDILEDGER_SMTP_PORT` (default 465), `KUDILEDGER_SMTP_USER`, `KUDILEDGER_SMTP_FROM` and `KUDILEDGER_SMTP_PASSWORD_FILE`. Provide the SMTP password through a protected file readable by the service, such as a systemd credential. The app verifies the SMTP TLS certificate. Verify deliverability and sender identity before approving real email.

Public TLS, encrypted off-host backups with a tested restore, and independent external monitoring are required before real pilot entries. Review the [release gate and rollback procedure](release-candidate.md) before applying the deployment files.
