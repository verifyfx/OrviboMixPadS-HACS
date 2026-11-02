# Changelog

## 0.2.0 — 2026-11-02

- Add IP-first MixPad setup: enter a panel IP and account, then import its
  supported lights with their actual IDs and endpoints from cloud inventory.
- Match a nonempty handshake UID or unique cloud IP association. When blank-UID
  firmware has no unique cloud address match, offer a list of panels described
  by their connected lights instead of asking for IDs or JSON.
- Configure additional panel IPs through options while preserving existing
  panels. Scope ongoing entity reconciliation to configured panels for new entries.
- Preserve legacy entries and the advanced local-only metadata path. Reject
  conflicting nonempty identities and keep power commands out of setup probes.

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
