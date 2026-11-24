# KLD-006C3 validation report

**Review decision pending. Real trader onboarding is NO-GO.**

The feature branch starts at `a158a44b1f5919b2a70daced540d6d8a82974609`, the KLD-006C2 merge on `main`. Its GitHub Actions workflow passed. The active ruleset requires a pull request and the GitHub Actions `release-gate` on a current branch, and prevents force pushes and deletion. The ruleset requires zero approving reviews, so independent review and owner approval still need to be recorded. [Merged base run](https://github.com/AgbajiAlexander/kudiledger_AI/actions/runs/45240172020) · [Effective branch rules](https://api.github.com/repos/AgbajiAlexander/kudiledger_AI/rules/branches/main)

| Verification | Evidence or remaining condition |
| --- | --- |
| Local Caddy config and systemd units | Independently validated checked-in files on Windows and Ubuntu WSL. The scheduled backup calendar evaluates to 02:00 Lagos time. |
| Synthetic automated validation | Windows full suite passed 225 tests in 133.864 seconds. It included the new host preflight tests, a real loopback TLS proxy exercise, local Chromium and interrupted-save recovery, and isolated SQLite restore. Four focused preflight tests also passed on Ubuntu WSL, including real POSIX permission checks. CI evidence is attached to the feature PR. |
| Physical Android | Awaiting two performed and witnessed device runs including a low-cost phone. [Walkthrough](android-device-validation.md) · [Evidence template](android-device-evidence.md) |
| Physical printing and carrier behavior | Awaiting representative printer and actual mobile-link observation. USB reverse isolation and browser emulation cannot establish print or carrier behavior. |
| Approved host and provider | Public DNS, public TLS renewal, port reachability, installed service identity and permissions, SMTP sender ownership, alert routing, encrypted off-host transfer and timed restore remain unverified. [Preflight](infrastructure-preflight.md) |
| Release sign-off | Independent reviewer, operational primary and alternate, approved spend, and product-owner acceptance are open gates. |

The proposed hosting baseline is US$19.40 monthly, before supplemental services and taxes. Review the transfer runner and backup protection costs in the approved checkout. Keep storage credentials off the application host; the scoped Spaces write credential also permits deletion. Commissioning remains exposed to a single compute host outage until a timed isolated restore is observed. No provider resources, public listeners, DNS records or actual emails were created for this validation.
