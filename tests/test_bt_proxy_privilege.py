"""Tests for the pieces that close the reconnect race with Steam over the
real DualSense's hidraw node (see bt_hid_proxy.py's open_real_device() and
_set_real_device_lock_marker()). The setcap'd helper's actual privileged
behavior (bypassing DAC, touching /run) can't be exercised without root and
the real binary - not covered here - but _open_via_helper()'s own fd-receipt
logic (SCM_RIGHTS framing) is fully real: it runs a genuine UNIX socketpair
and hands a real, independently-verifiable fd across it, with only the
*subprocess* end faked."""
import array
import os
import socket
import subprocess
import types

import pytest

import bt_hid_proxy as bt


class TestKickRealDevice:
    """_kick_real_device() is what recovers a real device Steam already had
    open from *before* the lock marker ever existed - chmod alone can never
    revoke an already-open fd, only block new opens. Best-effort by design:
    a failure here must never block attach() from proceeding anyway."""

    def test_root_writes_unbind_then_bind_directly_no_subprocess(self, monkeypatch):
        """Root (the Deck plugin) needs this exactly as much as an
        unprivileged desktop process does - an already-open fd survives a
        root chmod too - but it can do the unbind/bind itself, no setcap'd
        helper involved."""
        monkeypatch.setattr(bt.os, "geteuid", lambda: 0)
        subprocess_calls = []
        monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: subprocess_calls.append(a))

        writes = []

        class FakeFile:
            def __init__(self, path):
                self.path = path
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def write(self, data):
                writes.append((self.path, data))

        monkeypatch.setattr(bt, "open", lambda path, mode: FakeFile(path), raising=False)
        bt._kick_real_device("/sys/bus/hid/devices/0005:054C:0CE6.0010")

        assert subprocess_calls == []
        assert writes == [
            ("/sys/bus/hid/drivers/playstation/unbind", "0005:054C:0CE6.0010"),
            ("/sys/bus/hid/drivers/playstation/bind", "0005:054C:0CE6.0010"),
        ]

    def test_root_write_failure_does_not_raise(self, monkeypatch, capsys):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 0)
        def raise_it(path, mode):
            raise OSError("Отказано в доступе")
        monkeypatch.setattr(bt, "open", raise_it, raising=False)
        bt._kick_real_device("/sys/bus/hid/devices/0005:054C:0CE6.0010")  # must not raise
        assert "kick-real" in capsys.readouterr().out

    def test_unprivileged_asks_the_helper_for_this_exact_device(self, monkeypatch):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        calls = []
        monkeypatch.setattr(bt.subprocess, "run",
                            lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0))
        bt._kick_real_device("/sys/bus/hid/devices/0005:054C:0CE6.0010")
        assert calls == [[bt.HELPER_PATH, "kick-real", "0005:054C:0CE6.0010"]]

    def test_a_failed_helper_call_does_not_raise(self, monkeypatch, capsys):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            returncode=1, stderr="not the real DualSense/Edge's own hid device"))
        bt._kick_real_device("/sys/bus/hid/devices/0005:054C:0CE6.0010")  # must not raise
        assert "kick-real" in capsys.readouterr().out

    @pytest.mark.parametrize("exc", [OSError("no such helper"), subprocess.TimeoutExpired("cmd", 3)])
    def test_a_launch_failure_does_not_raise(self, monkeypatch, exc):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        def raise_it(*a, **k):
            raise exc
        monkeypatch.setattr(bt.subprocess, "run", raise_it)
        bt._kick_real_device("/sys/bus/hid/devices/0005:054C:0CE6.0010")  # must not raise


class TestRealDeviceLockMarker:
    def test_root_never_shells_out(self, monkeypatch):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 0)
        calls = []
        monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: calls.append(a))
        bt._set_real_device_lock_marker(True)
        bt._set_real_device_lock_marker(False)
        assert calls == []

    @pytest.mark.parametrize("enabled,word", [(True, "on"), (False, "off")])
    def test_unprivileged_asks_the_helper(self, monkeypatch, enabled, word):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        calls = []
        monkeypatch.setattr(bt.subprocess, "run",
                            lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0))
        bt._set_real_device_lock_marker(enabled)
        assert calls == [[bt.HELPER_PATH, "mark", word]]

    @pytest.mark.parametrize("exc", [OSError("no such helper"), subprocess.TimeoutExpired("cmd", 2)])
    def test_a_failed_helper_call_does_not_raise(self, monkeypatch, exc):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        def raise_it(*a, **k):
            raise exc
        monkeypatch.setattr(bt.subprocess, "run", raise_it)
        bt._set_real_device_lock_marker(True)  # must not raise


class TestOpenRealDevice:
    def test_root_opens_directly(self, monkeypatch):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 0)
        calls = []
        monkeypatch.setattr(bt.os, "open", lambda path, flags: calls.append((path, flags)) or 42)
        assert bt.open_real_device("/dev/hidraw10") == 42
        assert calls == [("/dev/hidraw10", bt.os.O_RDWR)]

    def test_unprivileged_goes_through_the_helper(self, monkeypatch):
        monkeypatch.setattr(bt.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(bt, "_open_via_helper", lambda path: 99 if path == "/dev/hidraw10" else None)
        assert bt.open_real_device("/dev/hidraw10") == 99


class TestOpenViaHelper:
    """Exercises the real socketpair + SCM_RIGHTS path: only the subprocess
    itself is faked, standing in for the C helper by sending a real,
    independently-opened fd back over the socket it was handed."""

    def _fake_helper_sending(self, tmp_path, content=b"probe-data"):
        """Returns a subprocess.run replacement that, like the real helper,
        reads pass_fds[0], sends a freshly-opened fd carrying `content` over
        it via SCM_RIGHTS, and reports success."""
        probe = tmp_path / "probe"
        probe.write_bytes(content)

        def fake_run(cmd, pass_fds, capture_output, text, timeout):
            assert cmd[0] == bt.HELPER_PATH
            assert cmd[1] == "open-fd"
            assert cmd[3] == str(pass_fds[0])
            helper_fd = os.dup(pass_fds[0])  # a real subprocess wouldn't share ours
            try:
                helper_sock = socket.socket(fileno=helper_fd)
                try:
                    sent_fd = os.open(str(probe), os.O_RDONLY)
                    try:
                        helper_sock.sendmsg([b"F"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                                       array.array("i", [sent_fd]).tobytes())])
                    finally:
                        os.close(sent_fd)
                finally:
                    helper_sock.close()
            except OSError:
                os.close(helper_fd)
                raise
            return types.SimpleNamespace(returncode=0, stderr="")
        return fake_run

    def test_receives_a_real_working_fd(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bt.subprocess, "run", self._fake_helper_sending(tmp_path))
        fd = bt._open_via_helper(str(tmp_path / "unused-path"))
        try:
            assert os.read(fd, 64) == b"probe-data"
        finally:
            os.close(fd)

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        monkeypatch.setattr(bt.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
            returncode=1, stderr="not a Sony DualSense/Edge device"))
        with pytest.raises(bt.ProxyUnavailable, match="not a Sony DualSense/Edge device"):
            bt._open_via_helper("/dev/hidraw0")

    def test_helper_that_never_sends_anything_times_out_instead_of_hanging(self, monkeypatch):
        """A helper that exits successfully having sent nothing (the "empty
        ancdata" branch, real_fd's own os.open() somehow producing no error
        but also no fd - not something the actual C helper can do, but worth
        the process never hanging here regardless) is exercised by this same
        case: parent_sock never sees a real subprocess's inherited fd close,
        since none was actually spawned, so it can only ever resolve via the
        timeout below - which is exactly the regression this guards: an
        earlier version of this function used SOCK_DGRAM and no timeout, and
        an equivalent scenario hung this call, and the whole engine thread
        with it, forever."""
        monkeypatch.setattr(bt.subprocess, "run",
                            lambda *a, **k: types.SimpleNamespace(returncode=0, stderr=""))
        with pytest.raises(bt.ProxyUnavailable, match="could not receive fd"):
            bt._open_via_helper("/dev/hidraw10")

    def test_helper_launch_failure_raises(self, monkeypatch):
        def raise_it(*a, **k):
            raise OSError("helper not found")
        monkeypatch.setattr(bt.subprocess, "run", raise_it)
        with pytest.raises(bt.ProxyUnavailable, match="helper unavailable"):
            bt._open_via_helper("/dev/hidraw10")
