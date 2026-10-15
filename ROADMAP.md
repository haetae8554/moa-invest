# Development plan

## 1. Public repository baseline

- [x] Separate reusable order module, local UI and Chrome extension.
- [x] Exclude local configuration, OAuth cache, databases, screenshots and generated artifacts.
- [x] Use memory-only OAuth tokens by default; document explicit legacy file cache behavior.
- [x] Add public-tree checks and isolated CI tests.

## 2. Local web credential registration

- [x] Implement dedicated, atomic Moa credential storage using Windows Credential Manager.
- [x] Add a same-origin API and password-style form without credential read-back or browser persistence.
- [x] Apply the active-order, preview invalidation and execution-mode requirements in SECURITY.md.
- [x] Verify persistence/error cases with fake credential stores and fake broker transport.

## 3. Distribution

- [x] Add a Chrome side panel with open/close and symbol-sync pause controls.

- [x] Add a one-time Windows Chrome launcher registration and automatic hidden server startup.
- [x] Build an unsigned Windows helper with Python included, isolated self-check and checksum file.
- [ ] Sign the Windows distribution and validate install/update/uninstall on a clean PC.
- [x] Add extension usage/privacy guide and an offline demo with synthetic holdings and split calculations.
- [x] Prepare privacy disclosures, permission justifications, listing draft and review instructions.
- [x] Add allowlisted extension packaging and identity/permission checks to CI.
- [x] Capture a synthetic demo image for review; retain its explicit demo labeling.
- [ ] Finalize store image dimensions, publisher contact details and assigned store ID before submission.
- [ ] Verify the full bidirectional selection flow across Chrome versions and website changes.

Public repository visibility does not deploy the trading server or publish the extension to the Chrome Web Store.
