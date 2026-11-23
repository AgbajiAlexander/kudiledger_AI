# KLD-006C2 release verification

## Candidate manifest

| Item | Verified candidate |
| --- | --- |
| Repository and branch | AgbajiAlexander/kudiledger_AI, main |
| Merged release candidate | `c3344c69600e6d970c0a8da00376396d1df673f1` |
| Candidate feature parent | `0243226962f68a5e049fd8a1ccbdaa76751b88c3` |
| Previous main parent | `c1aa57c8a95a21bf2b92064d021f2256592d4574` |
| Complete Python dependency set | [requirements.txt](../requirements.txt), SHA-256 `750ad9cec46b301aaf1335c7b9938e99e43167af7482c185c8487b950a3d83d9` |
| CI runtime | Ubuntu 24.04, Python 3.13.18, Node 24.22.3 and Caddy 2.11.9. GitHub runner supplies Chrome. |
| Operating requirements | Single Uvicorn process and local durable SQLite on Ubuntu 24.04, Caddy in front, public DNS and TLS for the eventual host, restricted service accounts, SMTP over TLS, encrypted off-host backups and external monitoring. |

The candidate branch tree and merged tree were identical. The full suite passed on the clean merged checkout with **219 tests in 135.416 seconds**. This included the real local TLS integration at 390 and 1440 px, account reset revocation, browser print rendering, recovery and isolated restore. Dependency consistency, shell syntax and local WSL systemd validation passed. GitHub Actions on the exact merged SHA also passed **219 tests in 54.416 seconds**, dependency review and the required `release-gate`. [Merged commit](https://github.com/AgbajiAlexander/kudiledger_AI/commit/c3344c69600e6d970c0a8da00376396d1df673f1) · [CI run](https://github.com/AgbajiAlexander/kudiledger_AI/actions/runs/45230194137)

For an independently approved release, identify the final protected `main` SHA in the rollout record, verify that commit's gate, use the locked dependencies with `python -m pip install -r requirements.txt && python -m pip check`, and retain the [validated staging configuration](../deploy/staging/) and [release operations notes](release-candidate.md) with that artifact. Record the host image, SQLite runtime version, actual runner Chrome version and restore evidence at approval. The candidate validation used synthetic data.

## Repository owner controls

Effective rules for `refs/heads/main` already require PRs, block force pushes and deletion, and require the GitHub Actions `release-gate` check against an up-to-date branch. Ruleset 27923539 currently requires **zero approving reviews**. Confirm the protected branch requirement in the PR merge panel and retain the evidence with the rollout record. [Effective rules API](https://api.github.com/repos/AgbajiAlexander/kudiledger_AI/rules/branches/main)

1. As repository owner, open **Settings → Rules → Rulesets**, open the active ruleset protecting `main`, confirm enforcement is **Active**, and inspect the bypass list. Public ruleset metadata does not expose bypass actors.
2. Keep **Require a pull request before merging**, **Require status checks to pass**, **Require branches to be up to date** and the `release-gate` check sourced from GitHub Actions. Keep force-push and deletion restrictions enabled.
3. To enforce technical review in GitHub, set required approvals to at least one, select dismissal of stale approvals, and require approval of the most recent reviewable push by someone other than the pusher. Record product-owner approval separately unless a distinct approver policy is configured. The owner should review all bypass actors before approving any release.
4. On a feature PR, observe the blocked/pending state before checks are complete, the green `release-gate` on the current commit, then the required review state once review enforcement is enabled. If the branch falls behind, update it normally and require the new check result. Keep the PR open for independent review and product-owner approval. [GitHub ruleset controls](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

## Chrome scope

CI tries the standard Chrome sandbox first and probes startup. On supported GitHub-hosted Linux runners only, a failed probe can trigger a temporary AppArmor profile granting user-namespace permission to the exact canonical, root-owned Chrome executable under `/opt/google/chrome`. The shell removes the profile on normal exit and handled termination. The browser remains sandboxed. Hosted runner image and packaging changes can require revisiting the fallback. A hard-killed job depends on disposal of its ephemeral runner. The fallback belongs to the CI test step and may require runner sudo.
