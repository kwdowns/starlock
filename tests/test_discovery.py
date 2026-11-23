"""Tests for the Bonjour / mDNS advertiser (evf/discovery.py)."""

from evf.config.manager import ConfigManager
from evf.discovery import (
    SERVICE_TYPE,
    DiscoveryAdvertiser,
    instance_name,
    txt_properties,
)


class FakeZeroconf:
    def __init__(self, log):
        self.log = log
        self.registered = []

    def register_service(self, info, allow_name_change=False):
        assert allow_name_change
        self.registered.append(info)
        self.log.append(("register", tuple(info.parsed_addresses())))

    def unregister_service(self, info):
        self.registered.remove(info)
        self.log.append(("unregister", tuple(info.parsed_addresses())))

    def close(self):
        self.log.append(("close",))


def make(addresses, log, **kw):
    box = {"addrs": list(addresses)}
    adv = DiscoveryAdvertiser(
        8780,
        txt_properties("abcdef123456", "0.3.0-beta", 2),
        "abcdef123456",
        name="Starlock (test)",
        addresses=lambda: box["addrs"],
        zeroconf_factory=lambda: FakeZeroconf(log),
        **kw,
    )
    return adv, box


def test_txt_record_contents():
    props = txt_properties("id1", "0.3.0", 2)
    assert props == {
        "api": "1", "api_min": "1", "id": "id1", "path": "/", "ws": "/ws",
        "version": "0.3.0", "protocol": "2",
        "lx200": "4030", "stellarium": "10001",
    }
    assert "version" not in txt_properties("id1", None, None)


def test_instance_name_uses_short_hostname():
    assert instance_name("starlock.lan") == "Starlock (starlock)"
    assert instance_name(".") == "Starlock (starlock)"


def test_registers_service_with_port_server_and_addresses():
    log = []
    adv, _ = make(["192.168.77.1"], log)
    adv.refresh()
    info = adv._info
    assert info.type == SERVICE_TYPE
    assert info.name == f"Starlock (test).{SERVICE_TYPE}"
    assert info.port == 8780
    assert info.server == "starlock-abcdef.local."
    assert info.properties[b"id"] == b"abcdef123456"
    assert adv.advertised_addresses == ("192.168.77.1",)
    assert log == [("register", ("192.168.77.1",))]


def test_refresh_is_a_no_op_when_addresses_unchanged():
    log = []
    adv, _ = make(["10.0.0.5"], log)
    adv.refresh()
    adv.refresh()
    assert log == [("register", ("10.0.0.5",))]


def test_address_change_rebuilds_the_zeroconf_instance():
    log = []
    adv, box = make(["192.168.77.1"], log)
    adv.refresh()
    box["addrs"] = ["192.168.1.52", "192.168.77.1"]
    adv.refresh()
    assert log == [
        ("register", ("192.168.77.1",)),
        ("unregister", ("192.168.77.1",)),
        ("close",),
        ("register", ("192.168.1.52", "192.168.77.1")),
    ]


def test_no_address_withdraws_and_waits():
    log = []
    adv, box = make([], log)
    adv.refresh()
    assert log == [] and adv.registered_name is None
    box["addrs"] = ["192.168.77.1"]
    adv.refresh()
    box["addrs"] = []
    adv.refresh()
    assert log[-2:] == [("unregister", ("192.168.77.1",)), ("close",)]
    assert adv.advertised_addresses == ()


def test_thread_start_stop_unregisters():
    log = []
    adv, _ = make(["192.168.77.1"], log, refresh_s=0.01)
    adv.start()
    for _ in range(200):
        if log:
            break
        import time
        time.sleep(0.01)
    adv.stop()
    assert log[0] == ("register", ("192.168.77.1",))
    assert log[-2:] == [("unregister", ("192.168.77.1",)), ("close",)]


def test_device_id_is_generated_once_and_persisted(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path)
    first = cfg.device_id
    assert len(first) == 32
    assert cfg.device_id == first
    assert ConfigManager(config_dir=tmp_path).device_id == first


def test_discovery_enabled_default(tmp_path):
    assert ConfigManager(config_dir=tmp_path).discovery_enabled is True
