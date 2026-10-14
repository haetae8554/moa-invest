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

- [ ] Provide a guided local installation/update workflow.
- [ ] Prepare extension icons, screenshots, privacy disclosures and store review instructions.
- [ ] Verify the full bidirectional selection flow across Chrome versions and website changes.

Public repository visibility does not deploy the trading server or publish the extension to the Chrome Web Store.
