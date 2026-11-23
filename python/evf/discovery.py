"""Bonjour / mDNS advertising, so phone apps can find Starlock on the LAN.

The web server is announced as ``_starlock._tcp`` on its real port, with a
TXT record that tells a client what it found before it connects::

    api=1                 # discovery/API contract version (bump on breaking change)
    api_min=1             # oldest app API version this engine still serves
    id=<hex>              # stable per-install id (config.json "device.id")
    version=0.4.0         # app version from data/VERSION.json
    protocol=<n>          # camera/app protocol version from VERSION.json
    path=/                # web UI path on the advertised port
    ws=/ws                # state WebSocket path
    lx200=4030            # LX200 server port (SkySafari etc.)
    stellarium=10001      # Stellarium binary-protocol port

An iOS app browses with ``NWBrowser(for: .bonjour(type: "_starlock._tcp",
domain: nil))`` (and lists ``_starlock._tcp`` in ``NSBonjourServices``);
Android uses ``NsdManager.discoverServices("_starlock._tcp", ...)``.

The advertiser runs its own thread. The set of IPv4 addresses is polled
every ``refresh_s``: on the Pi the hotspot or Wi-Fi link can come up after
the service starts, or move between networks. When the set changes the
Zeroconf instance is rebuilt, because it only joins the multicast group
on interfaces that existed when it was created. The SRV target is a
per-install host name (``starlock-<id6>.local.``), so it never fights
avahi-daemon over the Pi's own ``starlock.local`` name.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_starlock._tcp.local."
API_VERSION = "1"
# Oldest API version an app may speak and still be served. Raise it only when
# support for that version is removed; apps then say the app needs updating.
API_MIN_VERSION = "1"

# Interfaces whose addresses aren't reachable from a phone on the LAN.
_SKIPPED_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "vnet", "tailscale", "zt",
    "vethernet", "hyper-v", "loopback",
)


def _usable(ip: str) -> bool:
    return bool(ip) and ip != "0.0.0.0" and not ip.startswith(("127.", "169.254."))


def lan_ipv4_addresses() -> list[str]:
    """Sorted IPv4 addresses of interfaces a phone could reach."""
    import ifaddr

    found: set[str] = set()
    for adapter in ifaddr.get_adapters():
        names = (str(adapter.name).lower(), str(adapter.nice_name).lower())
        if any(n.startswith(_SKIPPED_PREFIXES) for n in names):
            continue
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and _usable(ip.ip):
                found.add(ip.ip)
    return sorted(found)


def instance_name(hostname: str | None = None) -> str:
    """Human-readable service instance name, e.g. ``Starlock (starlock)``."""
    host = (hostname or socket.gethostname()).split(".")[0] or "starlock"
    return f"Starlock ({host})"


def txt_properties(
    device_id: str,
    version: str | None,
    protocol: str | int | None,
    lx200_port: int | None = 4030,
    stellarium_port: int | None = 10001,
) -> dict[str, str]:
    props = {
        "api": API_VERSION,
        "api_min": API_MIN_VERSION,
        "id": device_id,
        "path": "/",
        "ws": "/ws",
    }
    if version:
        props["version"] = str(version)
    if protocol is not None:
        props["protocol"] = str(protocol)
    if lx200_port:
        props["lx200"] = str(lx200_port)
    if stellarium_port:
        props["stellarium"] = str(stellarium_port)
    return props


class DiscoveryAdvertiser:
    """Keeps ``_starlock._tcp`` registered while the engine runs."""

    def __init__(
        self,
        port: int,
        properties: dict[str, str],
        device_id: str,
        *,
        name: str | None = None,
        addresses: Callable[[], Iterable[str]] = lan_ipv4_addresses,
        zeroconf_factory: Callable[[], object] | None = None,
        refresh_s: float = 30.0,
    ) -> None:
        self._port = port
        self._properties = dict(properties)
        self._name = name or instance_name()
        self._server = f"starlock-{device_id[:6]}.local."
        self._addresses = addresses
        self._factory = zeroconf_factory or _default_zeroconf
        self._refresh_s = refresh_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._zc = None
        self._info = None
        self._current: tuple[str, ...] = ()

    @property
    def advertised_addresses(self) -> tuple[str, ...]:
        with self._lock:
            return self._current

    @property
    def registered_name(self) -> str | None:
        with self._lock:
            return self._info.name if self._info is not None else None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="discovery", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._teardown()

    # -- internals ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception as exc:  # keep advertising attempts alive
                logger.warning("mDNS advertising failed: %s", exc)
                self._teardown()
            self._stop.wait(self._refresh_s)

    def refresh(self) -> None:
        """Register, re-register or withdraw to match the current addresses."""
        addrs = tuple(sorted(set(self._addresses())))
        with self._lock:
            if addrs == self._current and (self._info is not None or not addrs):
                return
        self._teardown()
        if not addrs:
            logger.info("mDNS: no LAN address yet, not advertising")
            return
        from zeroconf import ServiceInfo

        zc = self._factory()
        info = ServiceInfo(
            SERVICE_TYPE,
            f"{self._name}.{SERVICE_TYPE}",
            port=self._port,
            properties=self._properties,
            server=self._server,
            parsed_addresses=list(addrs),
        )
        zc.register_service(info, allow_name_change=True)
        with self._lock:
            self._zc, self._info, self._current = zc, info, addrs
        logger.info("mDNS: advertising %s on %s port %d",
                    info.name, ", ".join(addrs), self._port)

    def _teardown(self) -> None:
        with self._lock:
            zc, info = self._zc, self._info
            self._zc, self._info, self._current = None, None, ()
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception as exc:
            logger.debug("mDNS unregister failed: %s", exc)
        try:
            zc.close()
        except Exception as exc:
            logger.debug("mDNS close failed: %s", exc)


def _default_zeroconf():
    from zeroconf import InterfaceChoice, IPVersion, Zeroconf

    return Zeroconf(interfaces=InterfaceChoice.All, ip_version=IPVersion.V4Only)
