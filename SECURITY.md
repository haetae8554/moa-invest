# Security

This project is a local trading tool. It is not a hosted multi-user service and does not claim to be free of vulnerabilities.

## Credentials and local data

- Keep API credentials in Windows Credential Manager where possible. The local UI validates keys by reading brokerage accounts and stores the pair in the dedicated `moa-invest/toss-api/v1` target. Saved Moa credentials take precedence over legacy environment/vault settings.
- Never commit real `.env` files, API keys, OAuth tokens, account identifiers, databases, portfolio screenshots, logs or backups. `.env.example` contains blank credential values only.
- OAuth tokens stay in process memory by default. Setting `TOSS_TOKEN_CACHE_PATH` explicitly enables a legacy plaintext token cache for compatibility with another local application. That file is sensitive even if the API client secret is absent. Keep it outside published content, restrict OS access, and do not put it in shared/synced directories.
- The existing Windows credential reader is scoped to the named Toss credential targets; it does not enumerate the credential store. Another program running as the same OS user may access those credentials. Protect the Windows session and installed extensions/software.
- Environment variables and `.env` remain compatibility options, not encrypted storage. Git ignore rules do not encrypt files and do not remove files that were previously committed.

## HTTP and extension boundary

The Python HTTP server binds to `127.0.0.1`. It validates Host/Origin, requires a request header for API access and a CSRF token for state changes. It serves only an allowlist of static files and does not return API credentials. The default page disallows framing. Only `/panel` permits framing, and only by the exact Chrome extension origin derived from the public `manifest.key`; Toss and arbitrary websites cannot frame it. The public key pins an extension identity and is not an authentication secret. Do not expose it through a public reverse proxy or bind it to a public interface.

The Chrome extension transfers selected symbols and stock-page paths. It does not receive the broker API client ID/secret, use the order API, or submit orders. Public stock metadata requests use `credentials: omit`. Unofficial website metadata endpoints can change or become unavailable.

## Local web credential registration

Registration is a form in the locally served Moa UI (also embedded in the trusted Chrome side panel), not a hosted website collecting brokerage credentials:

1. Accept keys only through a same-origin, CSRF-protected POST with bounded input. Do not put secrets in URLs, analytics, logs, error bodies or browser storage.
2. Store both values as one versioned record in a dedicated Moa Windows Credential Manager target with one `CredWriteW` call. Preserve the original application's credential namespace. The implementation follows [Microsoft's CREDENTIALW layout](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).
3. Return only configured/validation status, never saved key values. Clear form fields after submission; no read-back/reveal endpoint.
4. Serialize credential changes with order execution. Reject changes during active/uncertain orders, invalidate previews, reset token state and require fresh explicit execution enablement after a successful change.
5. Keep newly registered tokens in memory; ignore the legacy file-cache path for those credentials. UI registration is Windows-only; unsupported operating systems do not fall back to plaintext storage.
6. Persist a pending credential revision and disable execution before writing to the OS vault. Failure or a crash leaves execution blocked until explicit re-registration. Old service instances sharing the same data directory cannot operate with the new revision; restart them. Other applications and different data directories are outside this coordination boundary.
7. Tests use synthetic keys/brokers and cover validation/storage failure, pair atomicity, CSRF, secret-free responses, stale instances, active-order conflicts and extension frame/message boundaries. Real orders are not exercised.

## Chrome server launcher

The optional Windows Native Messaging host accepts exactly `{"action":"ensure-server"}` from the pinned extension origin, with a 1 KiB input limit. Only extension UI pages call it; content scripts and web messages cannot relay launch commands. It neither accepts arbitrary executable paths/arguments nor reads or returns credentials/account/order data. A fixed loopback health route does not call the broker or issue OAuth tokens.

The installer registers one current-user Chrome native host and writes machine-specific paths only under ignored `data/native-host/`. It does not install a startup task, elevate privileges, export Windows credentials or modify `.env`. The launcher serializes starts with a file lock, reuses a compatible server, refuses occupied/unrecognized ports and never kills a server. The server child uses Windows no-window and job-breakaway flags; failure to detach is reported rather than falling back to a process that may die when Chrome closes. Browser closure does not stop accepted batch work; use the existing stop control. PC shutdown can interrupt a batch and does not authorize replay.

Order IDs are opaque identifiers, **not evidence of encryption or anonymity**. They are not API credentials, but identify transactions and should be redacted along with symbols, sides, quantities, account identifiers and statuses in public screenshots or reports. Do not publish real examples in tests or documentation.

## Publishing checks

The offline extension demo uses synthetic values, no Chrome/native bridge, no persistence and no network transport; its CSP denies connections and frames. It is visibly labeled and available to all users, not a reviewer-specific alternate behavior. Its calculations do not bypass or replace the production broker validation.

`scripts/build_release.py` creates an allowlisted extension archive, checks permission/identity drift, and optionally builds an **unsigned** Python-included Windows helper in an isolated temporary workspace. Only static UI files are added as application data; user `.env`, vault contents and databases are not packaged. The bundled self-test runs without Python on PATH and touches only a temporary loopback HTTP server/static assets. It does not register the helper or read keys. Installation and the store review remain separate explicit steps. Public disclosure drafts are in `PRIVACY.md` and `docs/store/`.

Run `python scripts/check_public_tree.py --staged` before committing and `python scripts/check_public_tree.py` against the committed tree. The check blocks known local/private file paths and common secret formats without printing matched values. It is an additional guard, not a complete secret scanner. CI runs the same check and uses synthetic broker responses only.

GitHub's public-repository secret scanning and push protection provide additional coverage for supported patterns; do not rely on them to recognize every broker's credentials. If a real secret is published, revoke/rotate it first, then remove it from history and review its use.

## Reporting a vulnerability

Do not post credentials, account information or exploit details in a public issue. Use the repository's private vulnerability reporting channel when available. Include a minimal sanitized reproduction and affected version.
