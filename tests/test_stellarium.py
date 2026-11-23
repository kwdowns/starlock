# Copyright (C) 2026 Arun Venkataswamy
#
# This file is part of Starlock.
#
# Starlock is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Starlock is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Starlock. If not, see <https://www.gnu.org/licenses/>.

"""Tests for Stellarium protocol and TCP server (ACCEPTANCE_TESTS §J3)."""

import socket
import struct
import time
from unittest.mock import patch
from urllib.error import URLError

import pytest

from evf.engine.pointing import PointingState
from evf.stellarium.protocol import (
    _GOTO_FMT,
    _GOTO_LEN,
    _POSITION_LEN,
    decode_goto,
    encode_position,
)
from evf.stellarium.server import StellariumServer, rc_base_url, resolve_rc_host


# ---------------------------------------------------------------------------
# Protocol encode/decode
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_encode_length(self):
        msg = encode_position(ra_hours=6.0, dec_degrees=45.0)
        assert len(msg) == _POSITION_LEN

    def test_encode_decode_roundtrip(self):
        """Encode a position, then decode just the RA/Dec fields and verify."""
        ra_in, dec_in = 12.345, -67.89
        msg = encode_position(ra_in, dec_in)

        # Unpack the full 24-byte message
        length, mtype, ts, ra_raw, dec_raw, status = struct.unpack("<HHQIii", msg)
        assert length == 24
        assert mtype == 0
        assert status == 0

        # Reconstruct RA/Dec
        ra_out = ra_raw * (24.0 / 2**32)
        dec_out = dec_raw * (180.0 / 2**31)

        assert abs(ra_out - ra_in) < 0.001
        assert abs(dec_out - dec_in) < 0.001

    def test_encode_zero(self):
        msg = encode_position(0.0, 0.0)
        _, _, _, ra_raw, dec_raw, _ = struct.unpack("<HHQIii", msg)
        assert ra_raw == 0
        assert dec_raw == 0

    def test_encode_full_range(self):
        """RA=24h wraps to 0, Dec at ±90°."""
        msg_north = encode_position(0.0, 90.0)
        _, _, _, _, dec_raw, _ = struct.unpack("<HHQIii", msg_north)
        # 90° * (2^31 / 180) = 2^30
        assert dec_raw == 2**30

        msg_south = encode_position(0.0, -90.0)
        _, _, _, _, dec_raw, _ = struct.unpack("<HHQIii", msg_south)
        assert dec_raw == -(2**30)

    def test_decode_goto(self):
        ra_in, dec_in = 18.5, 30.0
        ra_raw = int(ra_in * (2**32 / 24.0)) & 0xFFFFFFFF
        dec_raw = int(dec_in * (2**31 / 180.0))
        ts = int(time.time() * 1_000_000)
        data = struct.pack(_GOTO_FMT, _GOTO_LEN, 0, ts, ra_raw, dec_raw)
        ra_out, dec_out = decode_goto(data)
        assert abs(ra_out - ra_in) < 0.001
        assert abs(dec_out - dec_in) < 0.001

    def test_decode_goto_wrong_size(self):
        with pytest.raises(struct.error):
            decode_goto(b"\x00" * 10)


# ---------------------------------------------------------------------------
# TCP server integration
# ---------------------------------------------------------------------------

def _connect(port: int, timeout: float = 2.0) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(("127.0.0.1", port))
    return sock


class TestStellariumServer:
    def test_start_stop(self):
        ps = PointingState()
        srv = StellariumServer(ps, port=0)
        srv.start()
        assert srv.port > 0
        srv.stop()

    def test_on_client_connected_called_per_connection(self):
        calls = []
        srv = StellariumServer(PointingState(), port=0,
                               on_client_connected=lambda: calls.append(1))
        srv.start()
        try:
            a, b = _connect(srv.port), _connect(srv.port)
            deadline = time.monotonic() + 3.0
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert len(calls) == 2
            a.close()
            b.close()
        finally:
            srv.stop()

    def test_client_connect_and_receive(self):
        """Inject known RA/Dec, connect a client, verify received message."""
        ps = PointingState()
        # RA in degrees, Dec in degrees (server converts RA to hours)
        ps.update(ra_j2000=180.0, dec_j2000=45.0, roll=0.0, matches=10, prob=0.05)

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            client = _connect(srv.port)
            # Wait for a broadcast (server sends at ~1 Hz)
            data = client.recv(1024)
            assert len(data) == _POSITION_LEN

            _, _, _, ra_raw, dec_raw, status = struct.unpack("<HHQIii", data)
            ra_hours = ra_raw * (24.0 / 2**32)
            dec_degrees = dec_raw * (180.0 / 2**31)

            # 180° = 12h
            assert abs(ra_hours - 12.0) < 0.01
            assert abs(dec_degrees - 45.0) < 0.01
            assert status == 0

            client.close()
        finally:
            srv.stop()

    def test_no_send_when_invalid(self):
        """If PointingState is not valid, server sends nothing."""
        ps = PointingState()  # valid=False by default

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            client = _connect(srv.port, timeout=3.0)
            # Wait longer than one broadcast interval
            time.sleep(1.5)
            client.setblocking(False)
            try:
                data = client.recv(1024)
                # If we got data it should be empty (connection still open but no messages)
                assert data == b"" or data is None
            except BlockingIOError:
                pass  # expected — no data available
            client.close()
        finally:
            srv.stop()

    def test_multiple_broadcasts(self):
        """Verify messages arrive at roughly 1 Hz."""
        ps = PointingState()
        ps.update(ra_j2000=45.0, dec_j2000=20.0, roll=0.0, matches=12, prob=0.03)

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            client = _connect(srv.port)
            msgs = []
            start = time.monotonic()
            while time.monotonic() - start < 3.5:
                try:
                    data = client.recv(_POSITION_LEN)
                    if data and len(data) == _POSITION_LEN:
                        msgs.append(data)
                except socket.timeout:
                    break
            client.close()

            # Should have received 2-4 messages in ~3.5 seconds
            assert len(msgs) >= 2, f"Expected >=2 messages, got {len(msgs)}"
        finally:
            srv.stop()

    def test_goto_logged_not_acted_on(self):
        """Send a GOTO message; verify PointingState is unchanged."""
        ps = PointingState()
        ps.update(ra_j2000=90.0, dec_j2000=30.0, roll=0.0, matches=10, prob=0.05)

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            client = _connect(srv.port)

            # Construct and send a GOTO message
            ra_raw = int(6.0 * (2**32 / 24.0)) & 0xFFFFFFFF
            dec_raw = int(-10.0 * (2**31 / 180.0))
            ts = int(time.time() * 1_000_000)
            goto_msg = struct.pack(_GOTO_FMT, _GOTO_LEN, 0, ts, ra_raw, dec_raw)
            client.sendall(goto_msg)

            # Wait for processing
            time.sleep(1.5)

            # PointingState should be unchanged
            snap = ps.read()
            assert snap.ra_j2000 == 90.0
            assert snap.dec_j2000 == 30.0

            client.close()
        finally:
            srv.stop()

    def test_client_disconnect_graceful(self):
        """Disconnect a client; server continues running and accepts new clients."""
        ps = PointingState()
        ps.update(ra_j2000=60.0, dec_j2000=10.0, roll=0.0, matches=10, prob=0.05)

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            # Connect and disconnect
            client1 = _connect(srv.port)
            client1.close()
            time.sleep(1.5)  # let server detect disconnect

            # Connect a second client — should still work
            client2 = _connect(srv.port)
            data = client2.recv(_POSITION_LEN)
            assert len(data) == _POSITION_LEN
            client2.close()
        finally:
            srv.stop()

    def test_multiple_clients(self):
        """Multiple clients receive the same broadcast."""
        ps = PointingState()
        ps.update(ra_j2000=120.0, dec_j2000=50.0, roll=0.0, matches=10, prob=0.05)

        srv = StellariumServer(ps, port=0)
        srv.start()
        try:
            client1 = _connect(srv.port)
            client2 = _connect(srv.port)

            data1 = client1.recv(_POSITION_LEN)
            data2 = client2.recv(_POSITION_LEN)

            assert len(data1) == _POSITION_LEN
            assert len(data2) == _POSITION_LEN

            # Both should have same RA/Dec (timestamps may differ slightly)
            _, _, _, ra1, dec1, _ = struct.unpack("<HHQIii", data1)
            _, _, _, ra2, dec2, _ = struct.unpack("<HHQIii", data2)
            assert ra1 == ra2
            assert dec1 == dec2

            client1.close()
            client2.close()
        finally:
            srv.stop()


# ---------------------------------------------------------------------------
# Remote Control host resolution
# ---------------------------------------------------------------------------

class TestRemoteControlHost:
    def test_setting_wins_over_peer(self):
        assert resolve_rc_host("stellarium-pc.local", "192.168.1.20") == "stellarium-pc.local"

    def test_setting_wins_even_without_client(self):
        assert resolve_rc_host("10.0.0.7", None) == "10.0.0.7"

    def test_peer_ip_is_the_default(self):
        assert resolve_rc_host("", "192.168.1.20") == "192.168.1.20"
        assert resolve_rc_host(None, "192.168.1.20") == "192.168.1.20"

    def test_loopback_peer_means_localhost(self):
        assert resolve_rc_host("", "127.0.0.1") == "localhost"
        assert resolve_rc_host("", "::1") == "localhost"

    def test_no_client_means_localhost(self):
        assert resolve_rc_host("", None) == "localhost"
        assert resolve_rc_host("   ", None) == "localhost"

    def test_ipv4_url(self):
        assert rc_base_url("192.168.1.20") == "http://192.168.1.20:8090"
        assert rc_base_url("pc.local", 8091) == "http://pc.local:8091"

    def test_ipv6_is_bracketed(self):
        assert rc_base_url("2001:db8::5") == "http://[2001:db8::5]:8090"
        assert rc_base_url("fe80::1%eth0") == "http://[fe80::1%25eth0]:8090"

    def test_server_url_uses_setting_then_peer(self):
        host = {"v": ""}
        srv = StellariumServer(PointingState(), port=0, rc_host=lambda: host["v"])
        assert srv._rc_url("192.168.1.20") == "http://192.168.1.20:8090"
        assert srv._rc_url(None) == "http://localhost:8090"
        host["v"] = "2001:db8::5"
        assert srv._rc_url("192.168.1.20") == "http://[2001:db8::5]:8090"

    def test_failing_setting_reader_falls_back(self):
        def boom():
            raise RuntimeError("config gone")
        srv = StellariumServer(PointingState(), port=0, rc_host=boom)
        assert srv._rc_url("192.168.1.20") == "http://192.168.1.20:8090"

    def test_requests_go_to_the_configured_host(self):
        urls = []

        def fake_urlopen(req, timeout=None):
            urls.append((req.full_url, timeout))
            raise URLError("no Stellarium here")

        with patch("evf.stellarium.server.urlopen", fake_urlopen):
            srv = StellariumServer(PointingState(), port=0, rc_host=lambda: "2001:db8::5")
            srv.start()
            try:
                client = _connect(srv.port)
                ra_raw = int(6.0 * (2**32 / 24.0)) & 0xFFFFFFFF
                dec_raw = int(-10.0 * (2**31 / 180.0))
                client.sendall(struct.pack(
                    _GOTO_FMT, _GOTO_LEN, 0, int(time.time() * 1_000_000), ra_raw, dec_raw))
                deadline = time.monotonic() + 4.0
                while len(urls) < 3 and time.monotonic() < deadline:
                    time.sleep(0.05)
                client.close()
            finally:
                srv.stop()

        # Threads left over from earlier tests may also hit the patched
        # urlopen (with localhost); only look at this server's requests.
        ours = [(u, t) for u, t in urls if "2001:db8::5" in u]
        assert ours, "no Remote Control request was made"
        assert all(u.startswith("http://[2001:db8::5]:8090/api/") for u, _ in ours)
        assert any(u.endswith("/api/main/status") for u, _ in ours)
        assert any(u.endswith("/api/objects/info?format=json") for u, _ in ours)
        assert all(t == 2.0 for _, t in ours)

    def test_loopback_client_without_setting_uses_localhost(self):
        urls = []

        def fake_urlopen(req, timeout=None):
            urls.append(req.full_url)
            raise URLError("no Stellarium here")

        with patch("evf.stellarium.server.urlopen", fake_urlopen):
            srv = StellariumServer(PointingState(), port=0)
            srv.start()
            try:
                client = _connect(srv.port)
                deadline = time.monotonic() + 3.0
                while not urls and time.monotonic() < deadline:
                    time.sleep(0.05)
                client.close()
            finally:
                srv.stop()

        assert urls
        assert all(u.startswith("http://localhost:8090/api/") for u in urls)

    def test_refresh_without_client_or_setting_does_nothing(self):
        urls = []
        with patch("evf.stellarium.server.urlopen",
                   lambda req, timeout=None: urls.append(req.full_url)):
            srv = StellariumServer(PointingState(), port=0)
            srv.refresh_remote_control()
            time.sleep(0.2)
        assert not any("8090" in u and "localhost" not in u for u in urls)
        assert srv._peers == {}
