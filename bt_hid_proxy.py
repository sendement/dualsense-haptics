"""Bluetooth HID proxy: clones the DualSense via /dev/uhid, hides the real
device from every other process (Steam included), relays its traffic through
the clone transparently, and merges our own audio-reactive rumble into
whatever Steam separately writes for triggers/lightbar before forwarding to
the real hardware - so native adaptive-trigger games and this app's own
vibration can coexist instead of one silently blocking the other.

Protocol/CRC/report-descriptor details below were reverse-engineered and
empirically validated (including a felt, working end-to-end test with real
audio-reactive vibration) as a throwaway prototype at
experiments/bt_hid_proxy_poc.py - this module ports that proven design into a
shared, importable component (identical between the desktop app and the Decky
plugin - see HapticsEngine._session_bt_proxy for the DSP/session loop that
drives it).
"""
import binascii
import fcntl
import glob
import json
import os
import select
import struct
import subprocess
import time
from pathlib import Path

RD = bytes.fromhex(
    "05010905a10185010930093109320935150026ff007508950481020939150025073500463b"
    "016514750495018142650005091901290e150025017501950e8102750695018101050109330934"
    "150026ff007508950281020600ff150026ff007508954d853109319102093b810285320932958d"
    "91028533093395cd910285340934960d01910285350935964d01910285360936968d0191028537"
    "093796cd01910285380938960d0291028539093996220291020680ff850509339528b102850809"
    "34952fb102850909249513b10285200926953fb10285220940953fb10285800928953fb1028581"
    "0929953fb1028582092a9509b1028583092b953fb10285f10931953fb10285f20932950fb10285"
    "f00930953fb10285f4092c953fb10285f5092d9507b10285f6092e962202b10285f7092f9507b1"
    "02c0"
)

UHID_DESTROY, UHID_START, UHID_STOP, UHID_OPEN, UHID_CLOSE, UHID_OUTPUT = 1, 2, 3, 4, 5, 6
UHID_GET_REPORT, UHID_GET_REPORT_REPLY, UHID_CREATE2, UHID_INPUT2 = 9, 10, 11, 12
BUS_BLUETOOTH, VENDOR, PRODUCT = 0x0005, 0x054C, 0x0CE6
HIDIOCGFEATURE_HDR = (3 << 30) | (0x48 << 8) | 0x07  # size filled in per-call

OUTPUT_CRC_SEED = 0xA2
FEATURE_CRC_SEED = 0xA3
DEFAULT_OUTPUT_REPORT = bytes([0x31, 0x10, 0x10] + [0] * 71 + [0] * 4)  # tag=0x10, like dualsensectl

# valid_flag0 (byte 3) bits gating the two trigger-effect field groups, per
# dualsensectl's DS_OUTPUT_VALID_FLAG0_{RIGHT,LEFT}_TRIGGER_MOTOR_ENABLE. The
# DualSense's output report is a full-state push, not a delta: any write
# whose valid_flag0 doesn't assert a given bit is telling the firmware "this
# write doesn't concern that field group" - the firmware then apparently
# treats the corresponding bytes as absent/reset rather than "leave as is".
# Games/Steam send frequent rumble-only writes (bit RIGHT_TRIGGER/LEFT_TRIGGER
# unset) interleaved with rare trigger-effect writes (bit set) - naively
# replacing the whole cached report on every write let the frequent
# rumble-only writes wipe out a trigger effect within milliseconds of it
# being set. Fixed by merging per-group instead of replacing wholesale: see
# BtHidProxySession._merge_incoming_output().
RIGHT_TRIGGER_FLAG = 0x04
LEFT_TRIGGER_FLAG = 0x08
RIGHT_TRIGGER_FIELD = slice(13, 24)   # motor_mode(1) + param[10]
LEFT_TRIGGER_FIELD = slice(24, 35)    # motor_mode(1) + param[10]

# valid_flag1 (byte 4) bits and field offsets for the Immersive Lighting
# visualizer (lightbar + the 5 player-indicator LEDs), per dualsensectl's
# DS_OUTPUT_VALID_FLAG1_{LIGHTBAR,PLAYER_INDICATOR}_CONTROL_ENABLE and its
# dualsense_output_report_common struct - offsets confirmed against
# dualsensectl's own source rather than guessed, and cross-checked against
# this file's own already-empirically-validated offsets (valid_flag0=3,
# RIGHT/LEFT_TRIGGER_FIELD, valid_flag2=41 all land exactly where that
# struct predicts once its 3-byte report_id/seq/tag header is accounted
# for).
LIGHTBAR_CONTROL_FLAG = 0x04
PLAYER_INDICATOR_CONTROL_FLAG = 0x10
PLAYER_LEDS_FIELD = 46
PLAYER_LEDS_INSTANT = 0x20
LIGHTBAR_RGB_FIELD = slice(47, 50)
# Bass (impacts/low end) reads as red, mid as green, treble ("airy"/high
# end) as blue - an arbitrary but intuitive association, not measured from
# anything. All three blend additively per channel (see
# apply_led_visualizer()), so e.g. a bass-and-treble-heavy moment reads as
# magenta and a full-spectrum moment approaches white, rather than any one
# band's color alone.
BASS_COLOR = (255, 0, 0)
MID_COLOR = (0, 255, 0)
TREBLE_COLOR = (0, 0, 255)

# Fixed identity for the clone's fake Bluetooth MAC, patched into feature
# report 9 (hid-playstation refuses to double-bind two devices sharing a real
# MAC). CLONE_UNIQ - what `dualsensectl -d <this>` (see triggers.py) needs to
# target the clone unambiguously instead of racing the real device's
# enumeration order - is derived from these same bytes, NOT the separate
# `uniq` field passed to UHID_CREATE2 below: confirmed empirically
# (`cat .../uevent` on the bound clone) that hid-playstation computes its own
# HID_UNIQ from the MAC it reads back via feature report 9, ignoring
# whatever uhid-level uniq string we hand it at creation time.
FAKE_MAC_BYTES = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01])
CLONE_UNIQ = ":".join(f"{b:02x}" for b in reversed(FAKE_MAC_BYTES))
CLONE_PHYS = "dualsense-haptics-proxy-clone"

HELPER_PATH = "/usr/lib/dualsense-haptics/dualsense-hidlock"
GROUP_NAME = "dualsense-haptics"

_STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "dualsense-haptics"
_LOCK_FILE = _STATE_DIR / "bt_hid_lock.json"


class ProxyUnavailable(Exception):
    """Raised when the clone/lockout machinery can't be set up - caller should
    fall back to the plain FF_RUMBLE path rather than leave the user with
    nothing."""


def sony_crc32(prefix_byte, payload):
    return binascii.crc32(bytes([prefix_byte]) + payload) & 0xFFFFFFFF


def _pad(b, n):
    b = b[:n]
    return b + b"\x00" * (n - len(b))


def hidiocgfeature(fd, report_id, bufsize=256):
    buf = bytearray(bufsize)
    buf[0] = report_id
    req = HIDIOCGFEATURE_HDR | (bufsize << 16)
    n = fcntl.ioctl(fd, req, buf, True)
    return bytes(buf[:n])


def build_create2():
    name = _pad(b"DualSense Wireless Controller", 128)
    phys = _pad(CLONE_PHYS.encode(), 64)
    uniq = _pad(CLONE_UNIQ.encode(), 64)
    rd_data = _pad(RD, 4096)
    body = struct.pack("<128s64s64sHHIIII", name, phys, uniq, len(RD), BUS_BLUETOOTH,
                        VENDOR, PRODUCT, 0x0100, 0) + rd_data
    return struct.pack("<I", UHID_CREATE2) + body


BASS_PRIORITY = 0.6  # default for the "bass_priority" led_visualizer config knob


def led_rgb_and_bar(led):
    """led = (bass_level, mid_level, treble_level, bass_priority), each
    level 0.0-1.0 - bundled into one tuple rather than four separate
    parameters since it threads through several call layers untouched.
    Returns ((r, g, b), lit) - lit being how many of the 5 player-indicator
    LEDs should be on, a left-to-right bar graph sized by whichever band is
    loudest. bass/treble are meant to be the same envelope magnitudes
    already driving the strong/weak rumble motors, reused rather than
    recomputed; mid has no motor to reuse from - see its own computation at
    each caller for why. The color blend is additive per channel
    (BASS_COLOR/MID_COLOR/TREBLE_COLOR, each scaled by its own band's level
    - see those constants' own comment), shared by both the Bluetooth HID
    Proxy's own report-byte path (apply_led_visualizer(), desktop only) and
    the plain sysfs LED class device path (write_led_sysfs() in
    haptics_engine.py, used wherever the proxy isn't available, e.g. the
    Decky plugin) so retuning the blend only ever needs doing once.

    bass_priority ducks mid/treble's contribution proportionally to the
    bass level before mixing - confirmed on real hardware that plain
    additive mixing let a bass peak wash out toward white whenever mid/
    treble were also present, when a hit should read as a clear, dominant
    red instead."""
    bass_level, mid_level, treble_level, bass_priority = led
    bass_level = max(0.0, min(1.0, bass_level))
    mid_level = max(0.0, min(1.0, mid_level))
    treble_level = max(0.0, min(1.0, treble_level))
    # The bar graph reflects true overall loudness - compute it before
    # ducking mid/treble below, which is a color-mix concern only.
    lit = round(max(bass_level, mid_level, treble_level) * 5)
    duck = 1.0 - max(0.0, min(1.0, bass_priority)) * bass_level
    mid_level *= duck
    treble_level *= duck
    rgb = tuple(
        min(255, round(bass_level * bc + mid_level * mc + treble_level * tc))
        for bc, mc, tc in zip(BASS_COLOR, MID_COLOR, TREBLE_COLOR)
    )
    return rgb, lit


def apply_led_visualizer(report, led):
    """Bluetooth HID Proxy report-byte variant of led_rgb_and_bar() - see
    there for the color/bar-graph math. Mutates `report` in place; caller
    still owns recomputing the CRC afterward. See command_lightbar3/
    command_player_leds in dualsensectl's source for the underlying
    protocol this mirrors."""
    rgb, lit = led_rgb_and_bar(led)
    report[4] |= LIGHTBAR_CONTROL_FLAG | PLAYER_INDICATOR_CONTROL_FLAG
    report[LIGHTBAR_RGB_FIELD] = bytes(rgb)
    report[PLAYER_LEDS_FIELD] = ((1 << lit) - 1) | PLAYER_LEDS_INSTANT


def merge_rumble(base_report, strong, weak, led=None):
    """base_report is whatever Steam/the driver last wrote (trigger effects,
    LED, everything) - only the two rumble-motor bytes and the two "select"
    valid-flag bits get overwritten with our own audio-reactive magnitude.
    Ground truth for which bits (HAPTICS_SELECT 0x02, not COMPATIBLE_VIBRATION
    0x01 as dualsensectl's own constant naming misleadingly suggests) came
    from sniffing a real, felt-working kernel FF_RUMBLE write over the air.
    led, if not None (see apply_led_visualizer() for its shape), also
    drives the Immersive Lighting visualizer - optional so callers that
    don't want it (or don't have BT proxy's exclusive device access to
    safely fight Steam's own lightbar writes) can leave the cached
    lightbar/LED state untouched."""
    report = bytearray(base_report)
    report[3] |= 0x02   # valid_flag0 |= DS_OUTPUT_VALID_FLAG0_HAPTICS_SELECT
    report[41] |= 0x04  # valid_flag2 |= DS_OUTPUT_VALID_FLAG2_COMPATIBLE_VIBRATION2
    report[6] = max(0, min(255, int(strong * 255)))  # motor_left (strong)
    report[5] = max(0, min(255, int(weak * 255)))    # motor_right (weak)
    if led is not None:
        apply_led_visualizer(report, led)
    body = bytes(report[:-4])
    crc = sony_crc32(OUTPUT_CRC_SEED, body)
    report[-4:] = crc.to_bytes(4, "little")
    return bytes(report)


def patch_report9_mac(fdata):
    """Feature report 9 carries the controller's own Bluetooth MAC at bytes
    1-6 (reversed) - hid-playstation refuses to bind a second dualsense
    sharing the real MAC ("Duplicate device found"), so the clone's copy gets
    a fake one. The trailing 4-byte CRC32 (prefix 0xA3, distinct from the
    0xA2 used for OUTPUT reports) must be recomputed after patching."""
    if len(fdata) < 7:
        return fdata
    fdata = fdata[:1] + FAKE_MAC_BYTES + fdata[7:]
    body = fdata[:-4]
    crc = sony_crc32(FEATURE_CRC_SEED, body)
    return body + crc.to_bytes(4, "little")


def find_real_hid_sys_path(require_driver_bound=True):
    """sysfs path for the genuine controller's hid instance, excluding any of
    our own clones (tagged with HID_PHYS=CLONE_PHYS in their uevent).

    require_driver_bound=False finds the hid instance as soon as it's
    registered on the bus, before hid-playstation's own probe() has
    finished attaching to it and before "DRIVER=playstation" appears in
    uevent - used for locking the real device down as fast as possible
    (see HapticsEngine._service_bt_proxy_idle()). This is safe because
    hidraw is a bus-level subsystem, not a driver-specific one: the node
    this looks for under sys_path/hidraw/ is usable for open()/chmod() the
    moment it exists, regardless of whether the specific hid_driver bound
    to it has finished its own initialization."""
    for sys_path in glob.glob("/sys/bus/hid/devices/0005:054C:0CE6.*") + \
            glob.glob("/sys/bus/hid/devices/0005:054c:0ce6.*"):
        uevent_path = os.path.join(sys_path, "uevent")
        if not os.path.exists(uevent_path):
            continue
        uevent = open(uevent_path).read()
        if CLONE_PHYS in uevent:
            continue
        if require_driver_bound and "DRIVER=playstation" not in uevent:
            continue
        return sys_path
    return None


def real_device_nodes(sys_path):
    """All /dev nodes belonging to the real controller's hid instance: hidraw
    (what Steam's native PS5 trigger/lightbar support writes to directly)
    plus every event*/js*/mouse* under its input children (gamepad, motion
    sensors, touchpad) - what SDL/evdev-based detection uses. Steam can use
    either path to find a real controller, so both need hiding."""
    nodes = []
    for hidraw in glob.glob(os.path.join(sys_path, "hidraw", "hidraw*")):
        nodes.append(f"/dev/{os.path.basename(hidraw)}")
    for handler in glob.glob(os.path.join(sys_path, "input", "input*", "*")):
        base = os.path.basename(handler)
        if base.startswith(("event", "js", "mouse")):
            nodes.append(f"/dev/input/{base}")
    return nodes


def find_clone_hidraw_path(timeout=2.0):
    """sysfs path for OUR OWN clone's hidraw node (tagged with
    HID_PHYS=CLONE_PHYS), for pointing SAxense's literal-PCM output at the
    clone instead of the real device - see BtHidProxySession.attach()'s
    caller. hid-playstation binds and creates the hidraw node asynchronously
    after UHID_CREATE2, so this polls briefly rather than assuming it exists
    immediately."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for sys_path in glob.glob("/sys/bus/hid/devices/0005:054C:0CE6.*") + \
                glob.glob("/sys/bus/hid/devices/0005:054c:0ce6.*"):
            uevent_path = os.path.join(sys_path, "uevent")
            if not os.path.exists(uevent_path):
                continue
            if CLONE_PHYS not in open(uevent_path).read():
                continue
            matches = glob.glob(os.path.join(sys_path, "hidraw", "hidraw*"))
            if matches:
                dev_path = f"/dev/{os.path.basename(matches[0])}"
                # sysfs and devtmpfs population aren't synchronized - the
                # sysfs entry above can appear before the /dev node exists.
                # Confirmed on real hardware that opening this path for
                # writing (via plain open(path, "wb"), which implies
                # O_CREAT) in that gap silently creates a regular file
                # instead of failing, permanently shadowing the real
                # character device the kernel registers moments later:
                # every future write - across every future proxy session,
                # not just this one - then goes into that dead file and
                # nowhere else. Only return a path that already exists as an
                # actual device node.
                if os.path.exists(dev_path):
                    return dev_path
        time.sleep(0.05)
    return None


# --- privilege backends ---------------------------------------------------

class PrivilegeBackend:
    def lock(self, nodes):
        """chmod every path in `nodes` to 0600. Returns {path: original_mode}
        for paths that were successfully changed."""
        raise NotImplementedError

    def restore(self, original_modes):
        """Best-effort chmod every path in `original_modes` back to its
        recorded mode."""
        raise NotImplementedError


class RootPrivilegeBackend(PrivilegeBackend):
    """Deck plugin: the backend already runs as root, so this just chmods
    directly - no helper subprocess needed."""

    def lock(self, nodes):
        original = {}
        for path in nodes:
            try:
                st = os.stat(path)
                os.chmod(path, 0o600)
                original[path] = st.st_mode & 0o777
            except OSError:
                pass
        return original

    def restore(self, original_modes):
        for path, mode in original_modes.items():
            try:
                os.chmod(path, mode)
            except OSError:
                pass


class HelperPrivilegeBackend(PrivilegeBackend):
    """Desktop: unprivileged process, shells out to the setcap'd C helper for
    the actual chmod. Reading the original mode first doesn't need elevated
    rights (world-readable stat)."""

    def _run_helper(self, mode_octal, paths):
        if not paths:
            return set()
        try:
            result = subprocess.run(
                [HELPER_PATH, oct(mode_octal)[2:], *paths],
                capture_output=True, text=True, timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ProxyUnavailable(f"helper unavailable: {e}") from e
        if result.returncode not in (0, 1):
            raise ProxyUnavailable(result.stderr.strip() or "helper failed")
        ok_paths = set()
        for line in result.stdout.splitlines():
            if line.startswith("OK "):
                ok_paths.add(line[3:].strip())
        return ok_paths

    def lock(self, nodes):
        original = {}
        for path in nodes:
            try:
                original[path] = os.stat(path).st_mode & 0o777
            except OSError:
                pass
        ok_paths = self._run_helper(0o600, list(original.keys()))
        if not ok_paths:
            raise ProxyUnavailable("helper could not lock any device node")
        return {p: m for p, m in original.items() if p in ok_paths}

    def restore(self, original_modes):
        # Best-effort per original mode value, since paths may need different
        # target modes if they somehow differed going in (they never do in
        # practice - all Sony device nodes share the same uaccess-granted
        # mode - but this stays correct if that ever changes).
        by_mode = {}
        for path, mode in original_modes.items():
            by_mode.setdefault(mode, []).append(path)
        for mode, paths in by_mode.items():
            try:
                self._run_helper(mode, paths)
            except ProxyUnavailable:
                pass


def make_privilege_backend():
    return RootPrivilegeBackend() if os.geteuid() == 0 else HelperPrivilegeBackend()


def preflight_check():
    """Cheap, non-destructive check for UI use before persisting the toggle.
    Does not guarantee success at actual runtime - group membership granted
    but not yet refreshed by a relogin still fails when the session opens
    /dev/uhid for real."""
    if not os.path.exists("/dev/uhid"):
        return False, "no_uhid_device"
    if os.geteuid() == 0:
        return True, ""
    if not os.access("/dev/uhid", os.R_OK | os.W_OK):
        return False, "no_uhid_access"
    if not os.access(HELPER_PATH, os.X_OK):
        return False, "no_helper"
    return True, ""


# --- crash-recovery / cross-process lock state -----------------------------

def _lock_state_path():
    return _LOCK_FILE


def write_lock_state(original_modes, pid):
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE.write_text(json.dumps({
        "pid": pid, "clone_uniq": CLONE_UNIQ, "original_modes": original_modes,
    }))


def read_lock_state():
    try:
        return json.loads(_LOCK_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def clear_lock_state():
    try:
        _LOCK_FILE.unlink()
    except OSError:
        pass


def is_proxy_active():
    """Returns CLONE_UNIQ if a proxy session is currently live (anywhere in
    this install - main process or a separate root subprocess), else None.
    Used by triggers.py to target dualsensectl at the clone instead of the
    now-hidden real device."""
    state = read_lock_state()
    return state.get("clone_uniq") if state else None


def recover_stale_lock():
    """Call once at process startup. If a lock file survives from an unclean
    shutdown (SIGKILL, crash), restore those permissions best-effort and
    clear the file - every individual chmod is safe even if the process that
    made it is long gone."""
    state = read_lock_state()
    if not state:
        return
    backend = make_privilege_backend()
    backend.restore(state.get("original_modes", {}))
    clear_lock_state()


# --- the session itself -----------------------------------------------------

class BtHidProxySession:
    """Owns exactly one running clone: the real hidraw fd, the /dev/uhid fd,
    the cached last-Steam-write, and the lock-out state. No audio/DSP here -
    that stays in HapticsEngine, which drives relay_input/relay_output_or_get_report
    /write_rumble on its own 20ms tick alongside the FF_RUMBLE path it
    replaces."""

    def __init__(self):
        self.real_fd = None
        self.uhid_fd = None
        self._backend = None
        self._original_modes = None
        self.last_steam_report = bytearray(DEFAULT_OUTPUT_REPORT)
        self.last_input_report = None

    def attach(self):
        """Locks out and opens the real device. The very first call also
        creates the uhid clone; later calls (after detach(), once the real
        device reconnects) only re-establish the real-device side and leave
        an already-existing clone untouched. This matters because Steam's
        controller detection does not treat "the same clone (same uniq)
        rebound after a destroy+recreate" as a reconnect of what it already
        knew about - confirmed on real hardware that *every* clone rebuild,
        whether from a plain Bluetooth reconnect or from toggling this
        feature off/on, left Big Picture/gamescope showing a second
        controller icon with doubled button presses alongside the first.
        Keeping the clone itself alive across real-device reconnects (this
        method) and real-device disconnects (see detach()) avoids that
        entirely - Steam only ever sees the clone bind once per engine
        run.

        Idempotent: a no-op if already attached, so a caller racing to lock
        the real device down as fast as possible (see
        HapticsEngine._service_bt_proxy_idle()) and the regular per-
        connection caller (HapticsEngine._session_bt_proxy()) can both call
        this without either one leaking the other's fd or clobbering the
        recorded original permissions with the already-locked (0600) mode."""
        if self.real_fd is not None:
            return
        # A few short retries: launching a game can make Steam Input
        # briefly renegotiate the controller's connection, during which the
        # real hid instance's sysfs path can transiently disappear for well
        # under a second - confirmed on real hardware that a single missed
        # lookup right at that moment was enough to trip ProxyUnavailable's
        # 30s fallback cooldown for something that had already resolved
        # itself a moment later.
        sys_path = None
        nodes = []
        for _ in range(5):
            # Locking down permissions only needs the hidraw node to exist,
            # not for hid-playstation's own probe() to have finished - see
            # find_real_hid_sys_path()'s require_driver_bound docstring. The
            # bus-level sys_path and its hidraw child can each lag slightly,
            # so keep retrying until both are actually there rather than
            # raising the moment the (still hidraw-less) sys_path shows up.
            sys_path = find_real_hid_sys_path(require_driver_bound=False)
            if sys_path:
                nodes = real_device_nodes(sys_path)
                if any("/hidraw" in n for n in nodes):
                    break
            time.sleep(0.2)
        if not sys_path:
            raise ProxyUnavailable("real DualSense hid instance not found")
        real_path = next((n for n in nodes if "/hidraw" in n), None)
        if not real_path:
            raise ProxyUnavailable("no hidraw node under the real hid instance")

        # Open the real hidraw FIRST, while it still has its normal
        # (uaccess-granted) permissions - Linux only checks permissions at
        # open() time, so an already-open fd keeps working after the lock
        # below chmods the node to 0600. This matters because on desktop,
        # our own engine and Steam run as the exact same unprivileged OS
        # user - DAC/ACL permissions cannot tell them apart, only "already
        # had it open" vs "didn't". Locking before opening (the original,
        # wrong order) would cut off our own access exactly like Steam's,
        # since the ACL mask reduction that blocks Steam's named-user grant
        # blocks ours too - confirmed empirically, not just in theory.
        try:
            real_fd = os.open(real_path, os.O_RDWR)
        except OSError as e:
            raise ProxyUnavailable(f"could not open real hidraw: {e}") from e

        backend = make_privilege_backend()
        original_modes = backend.lock(nodes)
        if real_path not in original_modes:
            try:
                os.close(real_fd)
            except OSError:
                pass
            backend.restore(original_modes)
            raise ProxyUnavailable("could not lock the real hidraw node")

        self.real_fd = real_fd
        self._backend = backend
        self._original_modes = original_modes

        if self.uhid_fd is None:
            try:
                self.uhid_fd = os.open("/dev/uhid", os.O_RDWR)
                os.write(self.uhid_fd, build_create2())
                # hid-playstation issues its own GET_REPORT for feature report 9
                # (MAC/pairing info) as part of binding the clone, immediately
                # after CREATE2 - confirmed on real hardware (dmesg: "Failed to
                # retrieve feature with reportID 9: -5", "Failed to create
                # dualsense") that if the caller goes on to do anything slow
                # before ever reading uhid_fd (resolving the clone's hidraw path
                # for SAxense can itself take up to ~2s, plus spawning parec/
                # SAxense), the kernel's own request can time out and fail that
                # bind attempt outright - the *next* attempt (a fresh reconnect)
                # usually succeeds since it isn't racing anything, which is
                # exactly the "dies once right after connecting, then fine"
                # pattern this fixes. Servicing uhid_fd here, before returning
                # control to the caller, answers that request promptly instead.
                deadline = time.monotonic() + 1.5
                quiet_until = time.monotonic() + 0.3
                while time.monotonic() < deadline and time.monotonic() < quiet_until:
                    readable, _, _ = select.select([self.uhid_fd], [], [], 0.1)
                    if readable:
                        self.relay_output_or_get_report()
                        quiet_until = time.monotonic() + 0.3
            except OSError as e:
                self._teardown_fds()
                self._backend.restore(self._original_modes)
                self._backend = None
                self._original_modes = None
                raise ProxyUnavailable(f"clone setup failed: {e}") from e

        write_lock_state(self._original_modes, os.getpid())

    def detach(self):
        """Releases the real device only - the uhid clone stays alive (see
        attach()) so Steam never sees it disappear. Safe to call even if
        attach() never succeeded."""
        if self.real_fd is not None:
            try:
                os.close(self.real_fd)
            except OSError:
                pass
            self.real_fd = None
        if self._backend is not None and self._original_modes is not None:
            self._backend.restore(self._original_modes)
        self._backend = None
        self._original_modes = None
        if self.uhid_fd is not None:
            write_lock_state({}, os.getpid())

    def destroy(self):
        """Full teardown: detaches from the real device if still attached,
        then destroys the clone itself. Only call this when the feature is
        being turned off or the engine is shutting down - not on a routine
        real-device disconnect, which should go through detach() instead so
        a later reconnect can attach() to the same, still-alive clone."""
        self.detach()
        if self.uhid_fd is not None:
            try:
                os.write(self.uhid_fd, struct.pack("<I", UHID_DESTROY))
            except OSError:
                pass
            try:
                os.close(self.uhid_fd)
            except OSError:
                pass
            self.uhid_fd = None
        clear_lock_state()

    def relay_input(self):
        """One non-blocking-caller-responsibility read of real_fd -> UHID_INPUT2
        into uhid_fd. Caller (HapticsEngine) is expected to have already
        select()ed/polled real_fd as readable."""
        data = os.read(self.real_fd, 256)
        self.last_input_report = data
        ev = struct.pack("<I", UHID_INPUT2) + struct.pack("<H", len(data)) + _pad(data, 4096)
        os.write(self.uhid_fd, ev)

    def heartbeat_input(self):
        """Re-sends the last known real INPUT report to the clone, unchanged
        - used while detached (real device disconnected, see detach()) to
        keep the clone looking alive to Steam. Confirmed on real hardware
        (Steam's own controller.txt log) that a detach gap with no input
        traffic at all makes Steam's own hidraw read time out ("Controller
        device closed after hid_read failure"), and the very next
        successful read - once we reattach and relay_input() resumes - gets
        treated as a brand new local device with its own fresh XInput slot,
        even though the clone itself was never destroyed: this is what
        actually produced the persistent duplicate icon, not clone
        recreation or the real device's exposure window (both fixed
        separately, see attach()/_service_bt_proxy_idle())."""
        if self.last_input_report is None or self.uhid_fd is None:
            return
        ev = (struct.pack("<I", UHID_INPUT2)
              + struct.pack("<H", len(self.last_input_report))
              + _pad(self.last_input_report, 4096))
        os.write(self.uhid_fd, ev)

    def relay_output_or_get_report(self):
        """One read of uhid_fd: caches a Steam OUTPUT write (report 0x31) for
        the next write_rumble() merge, passes through anything else
        untouched, and answers GET_REPORT by relaying from the real device
        (patching feature report 9's MAC first). Also called while detached
        (self.real_fd is None) - see HapticsEngine._service_bt_proxy_idle():
        the clone persists across a real-device disconnect, so something
        still has to drain uhid_fd during the gap or its bounded event queue
        fills up ("Output queue is full" in dmesg) from Steam's own writes
        continuing against a clone it still thinks is present. Anything that
        would otherwise need the real device just gets a harmless no-op/
        error response instead."""
        data = os.read(self.uhid_fd, 4 + 4096 + 256)
        (etype,) = struct.unpack_from("<I", data, 0)
        if etype == UHID_OUTPUT:
            size = struct.unpack_from("<H", data, 4 + 4096)[0]
            rtype = data[4 + 4096 + 2]
            report = data[4:4 + size]
            if rtype == 1 and len(report) == len(DEFAULT_OUTPUT_REPORT):
                self.last_steam_report = self._merge_incoming_output(report)
            elif self.real_fd is not None:
                os.write(self.real_fd, report)
        elif etype == UHID_GET_REPORT:
            req_id, rnum, rtype = struct.unpack_from("<IBB", data, 4)
            try:
                fdata = hidiocgfeature(self.real_fd, rnum) if rtype == 0 and self.real_fd is not None else b""
                err = 0 if self.real_fd is not None else 1
                if rnum == 9:
                    fdata = patch_report9_mac(fdata)
            except OSError:
                fdata, err = b"", 1
            reply = struct.pack("<I", UHID_GET_REPORT_REPLY) + \
                struct.pack("<IHH", req_id, err, len(fdata)) + _pad(fdata, 4096)
            os.write(self.uhid_fd, reply)
        # UHID_START/STOP/OPEN/CLOSE: no action needed.

    def _merge_incoming_output(self, report):
        """Merges a fresh OUTPUT write into the accumulated last_steam_report
        instead of replacing it wholesale - see the RIGHT_TRIGGER_FLAG comment
        above for why. Any field group whose valid_flag0 bit isn't asserted in
        this particular write keeps its previously-cached value (and the
        cached write keeps re-asserting that group's flag bit, since the
        DualSense's output report is a full-state push - a group has to be
        included in every write to stay active, not just the one that set it)."""
        merged = bytearray(report)
        incoming_flag0 = report[3]
        cached_flag0 = self.last_steam_report[3]
        spliced = False
        for flag, field in ((RIGHT_TRIGGER_FLAG, RIGHT_TRIGGER_FIELD), (LEFT_TRIGGER_FLAG, LEFT_TRIGGER_FIELD)):
            if not (incoming_flag0 & flag) and (cached_flag0 & flag):
                merged[field] = self.last_steam_report[field]
                merged[3] |= flag
                spliced = True
        if spliced:
            # Splicing fields from a different write invalidates the
            # incoming report's own trailing CRC (computed over its
            # original bytes) - recompute so the cache always holds a
            # self-consistent report, for callers besides write_rumble()
            # (which recomputes its own CRC anyway) that forward it as-is.
            body = bytes(merged[:-4])
            merged[-4:] = sony_crc32(OUTPUT_CRC_SEED, body).to_bytes(4, "little")
        return merged

    def write_rumble(self, strong_mag, weak_mag, led=None):
        merged = merge_rumble(self.last_steam_report, strong_mag, weak_mag, led)
        os.write(self.real_fd, merged)

    def forward_trigger_only(self, led=None):
        """Relays ONLY the cached trigger-effect fields (plus, optionally,
        the Immersive Lighting visualizer - a separate field group gated by
        its own valid_flag1 bits, so it doesn't touch the motor-arbitration
        conflict described below) to the real device - used when something
        else (SAxense's own, separate HID report) is driving the motors
        instead of write_rumble()'s envelope-based merge. Deliberately does
        NOT forward the rest of last_steam_report (rumble-motor bytes,
        HAPTICS_SELECT, ...): confirmed on real hardware that
        re-broadcasting the game's own cached rumble state at our own tick
        rate races SAxense's report for control of the same motors and
        drowns it out, even though both are technically distinct report
        IDs - the firmware appears to arbitrate them as one shared "who's
        driving the motors right now" channel. A report built from scratch
        with only the trigger (and lighting) fields set never touches
        that."""
        report = bytearray(DEFAULT_OUTPUT_REPORT)
        cached_flag0 = self.last_steam_report[3]
        for flag, field in ((RIGHT_TRIGGER_FLAG, RIGHT_TRIGGER_FIELD), (LEFT_TRIGGER_FLAG, LEFT_TRIGGER_FIELD)):
            if cached_flag0 & flag:
                report[3] |= flag
                report[field] = self.last_steam_report[field]
        if led is not None:
            apply_led_visualizer(report, led)
        body = bytes(report[:-4])
        report[-4:] = sony_crc32(OUTPUT_CRC_SEED, body).to_bytes(4, "little")
        os.write(self.real_fd, bytes(report))

    def _teardown_fds(self):
        if self.uhid_fd is not None:
            try:
                os.write(self.uhid_fd, struct.pack("<I", UHID_DESTROY))
            except OSError:
                pass
            try:
                os.close(self.uhid_fd)
            except OSError:
                pass
            self.uhid_fd = None
        if self.real_fd is not None:
            try:
                os.close(self.real_fd)
            except OSError:
                pass
            self.real_fd = None

