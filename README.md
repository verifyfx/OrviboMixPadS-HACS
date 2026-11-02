# ORVIBO MixPad S for Home Assistant

An experimental, independently developed integration for **type-1 on/off lamp
relays controlled through a MixPad S**. Commands travel over local TCP 8088.
Optional ORVIBO account access supplies inventory and assumed cloud states.
One connection serves all configured relays on a gateway.

Inspired by [mozzie1121/orvibo-lan-control](https://github.com/mozzie1121/orvibo-lan-control).
Developed with the help of **GPT-6.1 Sol**. This project has **no affiliation
with ORVIBO**, vendor approval, or guaranteed device compatibility.
See [license and attribution](THIRD_PARTY_NOTICES.md).

## Support and verification

The reference investigation verified Hello/login, on/off control acknowledgments
and pushed state on MixPad S / MixPadGSL firmware **5.4.1.311**. One lamp was
physically verified there. That evidence supports the wire protocol; this new
integration has not yet been deployed or tested on hardware.

Only inventory rows with integer `deviceType: 1`, a gateway UID, exact device ID
and an explicit relay endpoint become controllable lights. Endpoints can be 0,
1 or another actual inventory value; never substitute endpoint 0 by default.
Automatic cloud association additionally requires a MixPad `deviceType: 114`
row for the same gateway UID. Unsupported/missing metadata is skipped.

Brightness, color, scenes, scene-button events, locks, alarms, BLE, cameras,
infrared and other device types are unsupported. No local initial-state query
has been established. States begin unknown; a successful acknowledgment gives
assumed state and a matching local push confirms it. Reconnect clears state to
unknown. No complete WAN-blocked gateway/HA restart test has been performed.

## Installation

Target: Home Assistant **2026.3 or later** (local brand assets require 2026.3).
The Linux CI workflow tests with the Home Assistant version resolved by the
current `pytest-homeassistant-custom-component` package. Compatibility with all
versions from this target onward is not yet established.

For HACS, add [this repository](https://github.com/verifyfx/OrviboMixPadS-HACS)
as a custom repository with category **Integration**, then install it and
restart Home Assistant yourself. This is not a claim of HACS default-store
inclusion. Until a release has been published, use manual installation.

For manual installation, copy `custom_components/orvibo_mixpad` into your HA
configuration's `custom_components` directory, or extract `orvibo_mixpad.zip`
directly into `custom_components/orvibo_mixpad/`. Restart HA yourself. Add
**ORVIBO MixPad S** under Settings → Devices & services → Add integration.

## Configuration

Use the same username and original password as the ORVIBO account bound to the
gateway. Local login also requires account credentials, but local-only mode
never sends them to the cloud. One entry is allowed per exact account username;
configure multiple gateways in that entry.

**Local only:** leave cloud access disabled and provide topology JSON. Obtain
the gateway UID, exact device IDs and endpoints from your own known inventory
or a one-time cloud setup. No emulator, APK, cache extraction or decryption is
required. The integration does not currently enumerate child devices over LAN.
All values below are invented examples; replace them with your own metadata:

```json
{
  "gateways": {"your-gateway-uid": "192.168.50.20"},
  "relays": [
    {
      "uid": "your-gateway-uid",
      "deviceId": "your-first-relay-id",
      "endpoint": 0,
      "deviceType": 1,
      "deviceName": "First lamp"
    },
    {
      "uid": "your-gateway-uid",
      "deviceId": "your-second-relay-id",
      "endpoint": 1,
      "deviceType": 1,
      "deviceName": "Second lamp"
    }
  ]
}
```

**Cloud inventory:** explicitly enable account inventory/status and select the
server matching your app's account region. `usa.orvibo.com` was verified in the
reference investigation. `china.orvibo.com` is documented by upstream but has
not been tested here. Other hosts/regions are intentionally unavailable until
verified. `us.orvibo.com` is not the USA API. Redirects are always refused;
credentials are never retried through GET or a different server.

Cloud setup can use `{"gateways":{},"relays":[]}`. It discovers supported
account devices and cloud-recorded gateway addresses. You can add trusted IP
overrides using `{"gateways":{"your-gateway-uid":"192.168.50.20"},"relays":[]}`.
Cloud snapshots and gateway addresses are cached in HA for local startup.

**Gateway discovery:** bounded IPv4 UDP broadcast to port 10000 uses upstream's
`cmd86` format. Only known cloud/manual gateway UIDs are considered. A discovered
or cloud-recorded address must return the expected UID in its TCP handshake
before use. Conflicting identities are rejected. Announcements use a public
bootstrap key and are untrusted; this is not cryptographic peer authentication.
Firmware returning a blank handshake UID requires an explicitly entered trusted
IP override. Discovery does not find unknown child device IDs, cross VLANs, use
mDNS/SSDP, or scan subnets. Discovery is source-verified and simulated, not yet
verified against this hardware.

## Updates, options and state

Options control cloud consent, UDP discovery, trusted IP/manual relay metadata,
and the account refresh interval (900–86400 seconds, default 1800). A reload
applies options. Disable cloud to stop future cloud requests; cached topology
remains available locally. Changed credentials use HA's reauthentication flow.
To change account or region, remove and re-add the entry.

Each account shares its token and snapshots. Concurrent refreshes coalesce;
there are no per-entity polling timers. All accounts and setup flows share a
queue with at least two seconds between HTTP requests. Startup uses 5–20 seconds
of jitter; recurring refreshes add up to 15% jitter. Snapshots cache for 60 seconds.
Failures back off from 60 seconds to one hour; HTTP 429 pauses all requests for
at least 60 seconds and honors a longer `Retry-After` seconds or HTTP date.
Tokens live only in RAM and renew on expiry or once after a rejected API
session. Rejected login stops polling and requests reauthentication. These
limits reduce load and cannot guarantee avoidance of vendor rate limits/bans.

Reconciliation reads all returned account families and adds newly supported
relays without duplicating entity IDs. Explicit metadata changes can revoke
support or replace an endpoint; old entities become unavailable. Missing rows
do not remove devices. Names and endpoint IDs come from inventory, without
guessing another gateway when ownership is missing.

**Large-home limitation:** the inspected app and upstream use readtable
`pageIndex=0`; neither inspected implementation defines continuation. This
integration marks inventory completeness as unverified even on success and
never infers deletion from absence. It refuses responses announcing unsupported
continuation rather than repeatedly fetching page 0 or claiming full pagination.
Large-home pagination is unfinished research and may require manual metadata.

Local commands are serialized per gateway with at least one second between
attempts. A timed-out command is not retried automatically: it may already have
reached the relay. Cloud snapshots remain assumed, carry an internal timestamp,
and cannot overwrite a pending command, a local event after fetch start, or
newer local evidence. Cloud failures do not affect local connection availability.
Lights show unavailable when local control is disconnected, even if a cloud
snapshot exists. The `state_source` attribute distinguishes local push, local
command and cloud snapshot evidence.

## Troubleshooting and removal

- If no lights appear, check the strict support gate, exact endpoint metadata,
  account family and gateway association. Unsupported types are intentionally skipped.
- If discovered lights are unavailable, enter the gateway's current trusted IP,
  allow TCP 8088 from HA, and verify the username/password and UID. A DHCP
  reservation is recommended for blank-UID firmware.
- If discovery fails, check same-subnet UDP broadcast routing or disable it and
  use manual addresses. No subnet probing is attempted.
- Unknown state after startup is expected until a push, command or cloud state
  provides evidence. Local readtable and scene events are not advertised.
- Cloud failure with working local lamps is not a local-control failure. Verify
  the region; allow backoff to expire. Never post response bodies or credentials.
- Download integration diagnostics for aggregate counts only. Review all HA
  logs before sharing; general HA debug/HTTP tracing can include private data.
- Remove the integration entry through HA to stop tasks, remove subscriptions
  and delete its inventory cache. Remove files/HACS installation afterward if
  desired. HA backups may retain credentials and old caches.

## Security

The stored uppercase MD5 password digest is **password-equivalent**, not a safe
password vault. HA config entries and backups must be protected. The original
password is not retained by this integration after setup; tokens/session keys
remain in memory. Diagnostic output is allowlisted and contains no account,
gateway/device/family IDs, IPs, hashes, tokens, names or raw payloads.

Cloud uses HA's HTTPS session with certificate verification, no redirects,
timeouts and an 8 MiB response bound. Local transport uses the vendor's AES-ECB
protocol/public bootstrap key, without TLS or authenticated integrity. Run on
a trusted network. Only private LAN IPv4 gateway addresses are accepted.
No cloud power controls, arbitrary command services, resets, or automatic
retries of ambiguous power operations are exposed.

## Development and releases

See [CONTRIBUTING.md](CONTRIBUTING.md), [protocol evidence](docs/PROTOCOL.md),
and [release steps](RELEASING.md). All committed fixtures are invented. No
household profiles, credentials, app binaries or extraction artifacts belong
in this repository. Test and packaging commands contact no real hardware.

Packaging follows [HA integration structure](https://contributors.home-assistant.io/core/integrations/file-structure/),
[local custom integration brands](https://contributors.home-assistant.io/core/integrations/brands/)
and [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).
