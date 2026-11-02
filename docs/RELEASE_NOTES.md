Experimental ORVIBO MixPad S integration for Home Assistant 2026.3 or later.

Version 0.2.0 introduces IP-first setup: enter one MixPad's LAN IP and your
account, enable cloud inventory, and its supported lights are imported
automatically. No device IDs, endpoints or JSON are needed for this path.
Add more panel IPs through Configure. Blank-UID firmware uses a unique cloud
IP match or asks you to select a panel by its connected light names. Conflicting
nonempty identities are rejected. Existing entries retain their known panels;
enter their IPs in Configure to supply explicit trusted addresses.

Download **orvibo_mixpad.zip** below. For manual installation, extract its contents
into `custom_components/orvibo_mixpad/` under your Home Assistant configuration.
HACS uses the same ZIP asset. `SHA256SUMS` contains the archive checksum.

Features include shared local gateway connections for type-1 on/off relays,
optional account-wide cloud inventory/status, bounded UDP gateway discovery,
manual IP/metadata fallback, UI setup/options/reauth and redacted diagnostics.

The initial main-branch CI passed offline tests, Home Assistant tests, lint,
packaging, hassfest and HACS validation. The release workflow reruns these checks
before publishing. This implementation has not been deployed or tested on
physical hardware. The prior investigation supports the local protocol on
MixPad S / MixPadGSL firmware 5.4.1.311; it does not establish all-firmware compatibility.

Large-home pagination remains unresolved and inventory completeness is explicitly
unverified. Discovered addresses require matching TCP handshake identity; blank-UID
firmware needs an explicit trusted IP override. China cloud support is documented
by upstream only. Scenes, brightness/color and unsupported device types are excluded.
Read the README for configuration, security and support limits.

Independent project, with no ORVIBO affiliation. Inspired by
mozzie1121/orvibo-lan-control; developed with the help of GPT-6.1 Sol.
