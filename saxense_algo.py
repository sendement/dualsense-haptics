"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at https://mozilla.org/MPL/2.0/.

Ported to Python from SAxense (https://github.com/egormanga/SAxense,
https://apps.sdore.me/SAxense) by Sdore, itself released under MPL 2.0.
This file reproduces only the DualSense-over-Bluetooth haptics wire
protocol - the HID report layout (id 0x32) and its CRC32 variant - that
SAxense.c's own reverse-engineering established; nothing else from the
original project (its README, build tooling, etc.) is included here.

The rest of this project is MIT-licensed (see ../LICENSE) - only this
file, being a derivative of SAxense's own MPL-2.0 source, stays under
MPL 2.0. See haptics_engine.py's _SaxenseWriter for the integration
(threading/buffering/hidraw-write) that consumes these functions - none
of that is derived from SAxense.c, which never had to do any of it (it
just used a POSIX real-time timer and blocking stdio in its own process).

Report layout (empirically confirmed byte-for-byte against the real
SAxense binary's stdout, cross-checked against SAxense.c's own structs):

    offset  size  content
    0       1     report id (0x32)
    1       1     tag/seq (always 0 in the original - never set otherwise)
    2       9     control sub-packet: pid=0x11 byte, length=7, 7 bytes of
                  data ({0xFE,0,0,0,0,0xFF,counter} - counter free-runs,
                  wrapping mod 256, one per report)
    11      66    PCM sub-packet: pid=0x12 byte, length=64, 64 bytes of
                  interleaved-stereo signed-8-bit audio at SAMPLE_RATE
    77      61    zero padding
    138     4     CRC32 (little-endian) of bytes [0:138], using the
                  reflected polynomial 0xEDB88320 seeded not with the usual
                  0xFFFFFFFF but with ~0xEADA2D49 - a shorthand for
                  "standard CRC32 initialized by first feeding it a single
                  0xA2 byte", the same report-type-seeded CRC used
                  elsewhere in DualShock4/DualSense's Bluetooth HID reports
"""

SAMPLE_RATE = 3000
CHANNELS = 2
SAMPLE_SIZE = 64
REPORT_SIZE = 142

# Matches SAxense.c's timer: SAMPLE_SIZE bytes of interleaved-stereo 8-bit
# PCM at SAMPLE_RATE per channel is consumed every this many seconds.
TICK_INTERVAL_S = SAMPLE_SIZE / (SAMPLE_RATE * CHANNELS)  # ~0.0106667s

_REPORT_ID = 0x32
_CRC_INIT = (~0xEADA2D49) & 0xFFFFFFFF

_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ (0xEDB88320 if _c & 1 else 0)
    _CRC_TABLE.append(_c)


def _crc32_saxense(buf):
    crc = _CRC_INIT
    for b in buf:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (~crc) & 0xFFFFFFFF


# report_id, tag/seq=0, control-packet header (pid=0x11 packed with its
# `sized` bit -> 0x91, length=7), then the first 6 of the control packet's
# 7 data bytes - the 7th is the free-running counter, appended per-call.
_HEAD_FIXED = bytes((_REPORT_ID, 0x00, 0x91, 0x07, 0xFE, 0x00, 0x00, 0x00, 0x00, 0xFF))
# PCM-packet header: pid=0x12 packed with its `sized` bit -> 0x92, length=64.
_MID_FIXED = bytes((0x92, 0x40))
_PAD = bytes(61)


def build_report(counter, sample64):
    """Assemble one 142-byte DualSense haptics HID report (id 0x32) carrying
    one SAMPLE_SIZE-byte block of interleaved-stereo signed-8-bit PCM.
    `counter` is a free-running per-report sequence byte (wraps mod 256, one
    increment per call - matches SAxense.c's own counter byte)."""
    if len(sample64) != SAMPLE_SIZE:
        raise ValueError(f"sample64 must be exactly {SAMPLE_SIZE} bytes, got {len(sample64)}")
    body = _HEAD_FIXED + bytes((counter & 0xFF,)) + _MID_FIXED + bytes(sample64) + _PAD
    return body + _crc32_saxense(body).to_bytes(4, "little")
