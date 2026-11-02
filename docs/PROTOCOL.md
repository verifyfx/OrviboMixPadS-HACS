# Protocol evidence and boundaries

Research inspected 2026-11-02. No live hardware operations were performed while
building this integration. Private investigation material is not distributed.

## Local protocol

The reference investigation established TCP 8088 frames: `hd`, total length
uint16 BE, kind `pk`/`dk`, CRC32 ciphertext uint32 BE, 32-byte session ID,
AES-ECB/PKCS7 encrypted JSON. Hello uses public bootstrap key
`khggd54865SNJHGF`; successful Hello installs the returned session key before
the reader consumes the next DK frame. Login uses uppercase password MD5.
CRC32 is corruption detection, not authenticated integrity.

Only Hello (0), login (2), relay power (15), heartbeat (32) and pushed state
(42) are used by the TCP client. For type-1 relay power, value1 is 0 for on
and 1 for off. Commands include the exact UID, deviceId and actual endpoint.
Pushed state uses the same on/off inversion and must route uniquely. Successful
login on observed firmware may have blank UID; only explicit trusted hosts can
use that exception. A conflicting nonempty identity is always rejected.

The local initial-state query remains unresolved. Never substitute command 31;
the investigated app identifies it as reset. Scenes and scene-button events
remain unsupported.

## Discovery

Upstream source inspected:
[discovery.py](https://github.com/mozzie1121/orvibo-lan-control/blob/main/custom_components/orvibo_lan/lib/discovery.py),
blob `e1be04356911cd6192f5f2db9e06846e17d39062`.
It sends PK/bootstrap frames with unset space-filled session, command 86,
matching serial/uniSerial, clientType 1, serverRecord false and ver 5.1.3.309
to IPv4 broadcast UDP port 10000. Response UID and packet-source IP provide
candidates only. This implementation independently encodes that format,
rejects unknown UIDs/public sources/corrupt packets/conflicting candidates,
and requires subsequent TCP handshake identity for automatic addresses.
The protocol was verified in source, not against a physical gateway here.

## Cloud

Reference read-only investigation verified USA server OAuth POST and signed
family/readtable POST. Public signing key `nQ45RjPtOws96jmH` is used for
HMAC-SHA256 over sorted nonempty `key=value&` parameters followed by `key=`
and the signing key; the signature is uppercase hexadecimal.

Upstream [cloud_client.py](https://github.com/mozzie1121/orvibo-lan-control/blob/main/custom_components/orvibo_lan/lib/cloud_client.py),
blob `76ee9417b82f9c8f9f8b3fb95c7adfe959baccc5`, documents `deviceType` 114
MixPad association and `gateway.localStaticIP`/`ip`. Type-1 devices are
admitted only when exact UID ownership and integer endpoint are present.
China host comes from upstream packet constants and remains untested here.

Both inspected app `SyncTableData` and upstream client initialize pageIndex
to zero. No continuation loop or verified next-page contract was found.
The app processes `tableNameList` and returned tables, without establishing
large-home completeness. We cannot responsibly implement guessed pagination
or advertise it as verified. All snapshots remain completeness-unverified;
explicit continuation metadata is rejected atomically. No deletion by absence
is performed. A follow-up must establish actual continuation semantics and
test multiple real pages before lifting this limit.

## Required hardware follow-up

1. Opt-in test setup/unload/reauth on a disposable HA installation.
2. Verify UDP request/reply and UID handshake on supported firmware.
3. Verify cloud inventory schemas across account regions and a large home.
4. Validate two relay endpoints sharing one gateway connection, pushed states,
   reconnect behavior, DHCP changes and discovery/manual fallback.
5. With explicit permission, test WAN-blocked gateway plus HA restart. Confirm
   expected unknown state before first evidence; never infer scene support.
