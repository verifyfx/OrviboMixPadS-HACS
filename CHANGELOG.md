# Changelog

## 0.1.1 — 2026-11-02

- Publish the integration ZIP and checksum on the GitHub release page.
- Make the cache-expiry test independent of CI runner uptime. The v0.1.0
  release gate caught this test assumption before any release assets were published.

## 0.1.0 — 2026-11-02

- Initial experimental MixPad S type-1 on/off relay integration.
- Shared gateway connections, bounded reconnects, gateway-wide command pacing,
  push routing, cloud state-race protection and conservative additive inventory.
- Optional account cloud snapshots, UDP cmd86 candidate discovery and explicit
  trusted-IP/manual metadata fallback.
- UI setup/options/reauth, allowlisted diagnostics and HA inventory cache.
- Simulated protocol/cloud tests, HA lifecycle CI, hassfest/HACS validation,
  SemVer checks and draft release ZIP automation.
- Discovery hardware behavior, large-home pagination, additional regions and
  end-to-end HA compatibility remain unverified. No scene support is claimed.
