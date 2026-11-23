# Discovery (Bonjour / mDNS)

Starlock advertises its web server on the local network so the native phone
apps (and anything else) can find it without the user typing an IP address.
Implementation: `python/evf/discovery.py`, started by `Engine.startup_discovery()`
right after the web server. Switch off with `"discovery": {"enabled": false}`
in config.json.

## Service

| Field         | Value                                                     |
|---------------|-----------------------------------------------------------|
| Type          | `_starlock._tcp` (domain `local.`)                        |
| Instance name | `Starlock (<short hostname>)`, e.g. `Starlock (starlock)`. A clash on the LAN gets renamed by the responder (`Starlock (starlock) (2)`), so don't key on the name. |
| Port          | the web server port (`webserver.port`, default 8780)      |
| SRV target    | `starlock-<first 6 of id>.local.` — its own name, never the Pi's avahi `starlock.local` |
| Addresses     | every IPv4 address of a LAN-reachable interface (loopback, link-local, docker/bridge/VPN/Hyper-V adapters are left out). IPv6 is not advertised. |

## TXT record

| Key          | Example        | Meaning |
|--------------|----------------|---------|
| `api`        | `1`            | Version of this discovery + HTTP API contract. Bumped only on breaking changes; clients should refuse a higher major they don't know. |
| `api_min`    | `1`            | Oldest API version this engine still serves. An app whose own range doesn't reach it says the app needs updating; an app whose minimum is above `api` says the Starlock needs a software update. Missing = same as `api`. |
| `id`         | `3f2a…` (32 hex) | Stable per-install id (`device.id` in config.json, generated on first start). Use it to recognise a Starlock across IP changes and to pair with the cloud service. Also returned by `GET /api/version` as `device_id`. |
| `version`    | `0.4.0`        | App version (`data/VERSION.json`). |
| `protocol`   | `1`            | `protocol_version` from `data/VERSION.json`. |
| `path`       | `/`            | Web UI path on the advertised port. |
| `ws`         | `/ws`          | State WebSocket path. |
| `lx200`      | `4030`         | LX200 server port. |
| `stellarium` | `10001`        | Stellarium binary-protocol port. |

Clients must ignore keys they don't know.

`GET /api/version` returns the same two numbers as `api` and `api_min`
(integers), for apps given an address instead of a discovered service.
Engines from before November 2026 return neither: treat that as `api` 1.

## Compatibility

An app supports a range of API versions (lowest to highest). It works with a
Starlock when the two ranges overlap:

- engine `api` < app minimum: the Starlock's software is too old. The app says
  so and offers the Starlock's own web UI (served by the engine, so always the
  right version) and, once updates exist, an update.
- engine `api_min` > app maximum: the app is too old; it asks for an app
  update and offers the web UI the same way.

Raise `api` only for breaking changes, and keep `api_min` as low as the code
can carry, so a Starlock that sat on a shelf for years still works with a
current app. Additive changes (new fields, new endpoints) don't change either
number: apps must treat a missing field or a 404 as "not supported here".

## Behaviour

- Addresses are re-checked every 30 s. When the set changes (hotspot or Wi-Fi
  coming up late, joining another network) the advert is withdrawn and the
  Zeroconf instance rebuilt, since it only joins the multicast group on
  interfaces that existed when it was created. With no usable address nothing
  is advertised until one appears.
- On shutdown the service is unregistered (goodbye packets), so browsers drop
  it straight away instead of waiting for the TTL.
- On the Pi, python-zeroconf shares UDP 5353 with avahi-daemon, which keeps
  answering for `starlock.local` itself.

## Client notes

- **iOS:** browse with `NWBrowser(for: .bonjour(type: "_starlock._tcp", domain: nil), using: .tcp)`.
  Info.plist needs `NSBonjourServices = ["_starlock._tcp"]` and an
  `NSLocalNetworkUsageDescription`. Read the TXT record from the browse result's
  metadata; resolve with an `NWConnection` to the endpoint (or `NetService`).
- **Android:** `NsdManager.discoverServices("_starlock._tcp", NsdManager.PROTOCOL_DNS_SD, …)`,
  then resolve (`registerServiceInfoCallback` on API 34+) for host, port and
  attributes. Hold a `WifiManager.MulticastLock` while browsing.
- After resolving, confirm with `GET http://<addr>:<port>/api/version`, which
  must return `"app": "starlock"` and the same `device_id` as the TXT `id`.
