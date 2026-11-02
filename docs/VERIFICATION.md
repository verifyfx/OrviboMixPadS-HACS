# Verification record — 2026-11-02

Version: **0.1.0**, prepared locally; not published or deployed.

## Completed

- **25 offline tests passed** under existing Python 3.14.6 with cryptography.
  The fake TCP server binds loopback only. Cloud responses and discovery packets
  use invented fixtures; no real account or gateway was contacted.
- Tests cover framing fragmentation, CRC/session/kind validation, identity
  mismatch, blank-UID trusted-host exception, rejected login, nonzero endpoint,
  unsolicited state routing, push beating acknowledgment, shared command spacing,
  ambiguous timeout without replay, reconnect unknown state, reader cancellation,
  cloud signing, request coalescing/cache/token reuse, bounded token renewal,
  reauth-stop behavior, global 429/Retry-After pacing, exponential backoff,
  unsupported device filtering, incomplete pagination rejection and local/cloud
  state races.
- Simulated lifecycle tests cover additive inventory, shared gateways, unload,
  cloud failures preserving local availability, discovery address replacement
  without granting trust, explicit support revocation, partial inventory retention
  and newer cache precedence over setup inventory.
- Source syntax, SemVer/tag agreement, matching English translation, license
  copies and the release package file allowlist pass local validation.
- `dist/orvibo_mixpad.zip` and `dist/SHA256SUMS` built locally. ZIP roots contain
  only integration files, original icons and required license/attribution notices.
- Original icon visually inspected. Generic staged file list/privacy pattern
  review performed. No private source paths, profiles, credentials, binaries,
  household inventories or extraction artifacts are included.
- Destination was empty locally; Git initialized on `main` and origin attached
  to the requested repository. GitHub metadata reported size 0. No commit,
  source push, tag, GitHub release, HA deployment or restart was performed.

## Prepared but not executed here

- Real Home Assistant pytest suite: UI config/duplicate prevention, options,
  reauthentication, entity state, dynamic additions and unload.
- HTTPS transport tests: redirect refusal, password confined to POST body,
  response-size bound, sanitized JSON failures and server allowlist.
- Ruff, hassfest and HACS validation jobs. Their dependencies are absent locally;
  no new tools were installed. CI must run after an authorized publication.
- Tag-triggered draft GitHub release with notes, ZIP and checksum, gated by all
  validation jobs and matching `vX.Y.Z`/manifest versions. Remote description
  and topics remain maintainer publication steps.

## Research and hardware gaps

UDP cmd86/port 10000 format and cloud topology fields were checked against
upstream source under MIT. USA API behavior and local relay protocol are based
on the prior investigation. This new implementation's discovery and HA runtime
have not been validated on physical hardware. China host is upstream-documented
only; unsupported regions remain unavailable.

Large-home pagination remains unfinished research. Inspected app and upstream
request pageIndex 0 without a continuation implementation. Snapshots explicitly
remain completeness-unverified, explicit unknown continuation is refused, and
absence never deletes entities. See `PROTOCOL.md` for required follow-up.

The implementation does not claim scene support, all-firmware compatibility,
HACS default-store inclusion, vendor approval or a completed WAN-blocked restart
test. Hardware testing and publication need separate coordination.
