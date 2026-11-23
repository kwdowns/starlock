"""Wi-Fi signal warning: /proc/net/wireless parsing, smoothing, hysteresis."""

from evf.wifi_signal import WifiSignal, quality, read_levels

HEAD = ("Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n")


def write(path, level):
    path.write_text(HEAD + f" wlan0: 0000   41.  {level}.  -256        0      0      0    117      0        0\n")


def test_parse(tmp_path):
    f = tmp_path / "wireless"
    write(f, -69)
    assert read_levels(f) == {"wlan0": -69.0}
    f.write_text(HEAD + " wlan0: 0000   0.  0.  -256  0 0 0 0 0 0\n")  # access point / not associated
    assert read_levels(f) == {}
    assert read_levels(tmp_path / "missing") == {}


def test_quality_bands():
    assert [quality(v) for v in (-50, -65, -75, -85)] == ["good", "fair", "weak", "poor"]


def test_warns_after_sustained_weak_signal_and_clears_with_hysteresis(tmp_path):
    f = tmp_path / "wireless"
    t = [0.0]
    sig = WifiSignal(f, clock=lambda: t[0])

    def at(level, seconds):
        snap = None
        for _ in range(seconds):
            write(f, level)
            snap = sig.snapshot()
            t[0] += 1.0
        return snap

    assert at(-65, 5)["warn"] is False
    s = at(-82, 3)
    assert s["warn"] is False  # one dip doesn't warn: still averaging
    s = at(-82, 20)
    assert s["warn"] is True and s["quality"] == "poor" and s["level_dbm"] == -82
    assert at(-74, 25)["warn"] is True  # better, but not above the clear level
    assert at(-66, 25)["warn"] is False


def test_rate_limited_and_none_without_wifi(tmp_path):
    f = tmp_path / "wireless"
    t = [0.0]
    sig = WifiSignal(f, clock=lambda: t[0])
    assert sig.snapshot() is None
    write(f, -60)
    assert sig.snapshot() is None  # read less than a second ago
    t[0] = 1.5
    assert sig.snapshot()["avg_dbm"] == -60
