"""Unit tests for bt_hid_proxy's pure protocol/report-building layer.

The byte offsets and CRC seeds asserted here were reverse-engineered and
validated against real hardware (see bt_hid_proxy.py's own comments) - these
tests pin them so a refactor can't silently shift a field.
"""
import binascii
import struct

import bt_hid_proxy as bt


class TestSonyCrc32:
    def test_is_crc32_over_seed_plus_payload(self):
        payload = bytes(range(32))
        expected = binascii.crc32(bytes([bt.OUTPUT_CRC_SEED]) + payload) & 0xFFFFFFFF
        assert bt.sony_crc32(bt.OUTPUT_CRC_SEED, payload) == expected

    def test_seed_byte_changes_the_checksum(self):
        payload = b"\x00" * 10
        assert bt.sony_crc32(bt.OUTPUT_CRC_SEED, payload) != \
            bt.sony_crc32(bt.FEATURE_CRC_SEED, payload)

    def test_result_fits_uint32(self):
        assert 0 <= bt.sony_crc32(0xA2, b"\xff" * 100) <= 0xFFFFFFFF


class TestPad:
    def test_pads_short_input_with_zeros(self):
        assert bt._pad(b"abc", 6) == b"abc\x00\x00\x00"

    def test_truncates_long_input(self):
        assert bt._pad(b"abcdef", 3) == b"abc"

    def test_exact_length_untouched(self):
        assert bt._pad(b"abcd", 4) == b"abcd"


class TestBuildCreate2:
    def test_layout_matches_uhid_create2_struct(self):
        event = bt.build_create2()
        assert struct.unpack_from("<I", event)[0] == bt.UHID_CREATE2
        body_fmt = "<128s64s64sHHIIII"
        assert len(event) == 4 + struct.calcsize(body_fmt) + 4096

        name, phys, uniq, rd_size, bus, vendor, product, version, country = \
            struct.unpack_from(body_fmt, event, 4)
        assert name.rstrip(b"\x00") == b"DualSense Wireless Controller"
        assert phys.rstrip(b"\x00") == bt.CLONE_PHYS.encode()
        assert uniq.rstrip(b"\x00") == bt.CLONE_UNIQ.encode()
        assert rd_size == len(bt.RD)
        assert bus == bt.BUS_BLUETOOTH
        assert (vendor, product) == (0x054C, 0x0CE6)

        rd_field = event[4 + struct.calcsize(body_fmt):]
        assert rd_field[:len(bt.RD)] == bt.RD
        assert not any(rd_field[len(bt.RD):])

    def test_clone_uniq_derives_from_fake_mac_reversed(self):
        assert bt.CLONE_UNIQ == "01:00:ef:be:ad:de"


class TestLedRgbAndBar:
    def test_silence_is_dark(self):
        assert bt.led_rgb_and_bar((0.0, 0.0, 0.0, 0.6)) == ((0, 0, 0), 0)

    def test_pure_bass_reads_red_full_bar(self):
        assert bt.led_rgb_and_bar((1.0, 0.0, 0.0, 0.6)) == ((255, 0, 0), 5)

    def test_pure_mid_reads_green(self):
        assert bt.led_rgb_and_bar((0.0, 1.0, 0.0, 0.6)) == ((0, 255, 0), 5)

    def test_pure_treble_reads_blue(self):
        assert bt.led_rgb_and_bar((0.0, 0.0, 1.0, 0.6)) == ((0, 0, 255), 5)

    def test_full_bass_priority_ducks_other_bands_entirely(self):
        rgb, lit = bt.led_rgb_and_bar((1.0, 1.0, 1.0, 1.0))
        assert rgb == (255, 0, 0)
        assert lit == 5

    def test_zero_priority_blends_additively(self):
        rgb, _ = bt.led_rgb_and_bar((1.0, 0.0, 1.0, 0.0))
        assert rgb == (255, 0, 255)

    def test_bar_reflects_loudness_before_ducking(self):
        # treble ducked to invisible in the color mix, but the bar still
        # counts it as the loudest band
        _, lit = bt.led_rgb_and_bar((0.2, 0.0, 1.0, 1.0))
        assert lit == 5

    def test_out_of_range_levels_are_clamped(self):
        assert bt.led_rgb_and_bar((5.0, -1.0, 0.0, 0.6)) == ((255, 0, 0), 5)

    def test_partial_level_scales_bar(self):
        _, lit = bt.led_rgb_and_bar((0.6, 0.0, 0.0, 0.6))
        assert lit == 3


class TestApplyLedVisualizer:
    def test_sets_flags_rgb_and_player_bar(self):
        report = bytearray(bt.DEFAULT_OUTPUT_REPORT)
        bt.apply_led_visualizer(report, (1.0, 0.0, 0.5, 0.0))
        assert report[4] & bt.LIGHTBAR_CONTROL_FLAG
        assert report[4] & bt.PLAYER_INDICATOR_CONTROL_FLAG
        assert bytes(report[bt.LIGHTBAR_RGB_FIELD]) == bytes((255, 0, round(0.5 * 255)))
        lit = 5  # loudest band is bass at 1.0
        assert report[bt.PLAYER_LEDS_FIELD] == ((1 << lit) - 1) | bt.PLAYER_LEDS_INSTANT

    def test_preserves_other_bytes(self):
        report = bytearray(bt.DEFAULT_OUTPUT_REPORT)
        before = bytes(report)
        bt.apply_led_visualizer(report, (0.0, 0.0, 0.0, 0.6))
        changed = {i for i, (a, b) in enumerate(zip(before, report)) if a != b}
        assert changed <= {4, bt.PLAYER_LEDS_FIELD, 47, 48, 49}


class TestMergeRumble:
    def test_writes_motor_bytes_and_select_flags(self):
        merged = bt.merge_rumble(bt.DEFAULT_OUTPUT_REPORT, strong=0.5, weak=0.25)
        assert merged[6] == 127   # motor_left / strong
        assert merged[5] == 63    # motor_right / weak
        assert merged[3] & 0x02   # HAPTICS_SELECT
        assert merged[41] & 0x04  # COMPATIBLE_VIBRATION2

    def test_recomputes_trailing_crc(self):
        merged = bt.merge_rumble(bt.DEFAULT_OUTPUT_REPORT, 1.0, 0.0)
        expected = bt.sony_crc32(bt.OUTPUT_CRC_SEED, merged[:-4])
        assert merged[-4:] == expected.to_bytes(4, "little")

    def test_clamps_magnitudes(self):
        merged = bt.merge_rumble(bt.DEFAULT_OUTPUT_REPORT, strong=2.0, weak=-1.0)
        assert merged[6] == 255
        assert merged[5] == 0

    def test_preserves_base_report_fields(self):
        # a base report carrying a trigger effect: those bytes must survive
        base = bytearray(bt.DEFAULT_OUTPUT_REPORT)
        base[bt.RIGHT_TRIGGER_FIELD] = bytes(range(11))
        merged = bt.merge_rumble(bytes(base), 0.5, 0.5)
        assert merged[bt.RIGHT_TRIGGER_FIELD] == bytes(range(11))
        assert len(merged) == len(base)

    def test_base_report_object_is_not_mutated(self):
        base = bytes(bt.DEFAULT_OUTPUT_REPORT)
        bt.merge_rumble(base, 1.0, 1.0)
        assert base == bt.DEFAULT_OUTPUT_REPORT

    def test_led_argument_drives_visualizer(self):
        merged = bt.merge_rumble(bt.DEFAULT_OUTPUT_REPORT, 0.0, 0.0,
                                 led=(1.0, 0.0, 0.0, 0.6))
        assert bytes(merged[bt.LIGHTBAR_RGB_FIELD]) == bytes((255, 0, 0))
        assert merged[4] & bt.LIGHTBAR_CONTROL_FLAG

    def test_no_led_argument_leaves_lightbar_state_alone(self):
        merged = bt.merge_rumble(bt.DEFAULT_OUTPUT_REPORT, 0.0, 0.0)
        assert merged[4] == bt.DEFAULT_OUTPUT_REPORT[4]
        assert merged[bt.LIGHTBAR_RGB_FIELD] == bt.DEFAULT_OUTPUT_REPORT[bt.LIGHTBAR_RGB_FIELD]


class TestPatchReport9Mac:
    def _fake_report9(self):
        real_mac = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
        body = bytes([0x09]) + real_mac + bytes(9)
        crc = bt.sony_crc32(bt.FEATURE_CRC_SEED, body)
        return body + crc.to_bytes(4, "little")

    def test_replaces_mac_with_fake(self):
        patched = bt.patch_report9_mac(self._fake_report9())
        assert patched[1:7] == bt.FAKE_MAC_BYTES
        assert patched[0] == 0x09

    def test_recomputes_feature_crc(self):
        patched = bt.patch_report9_mac(self._fake_report9())
        expected = bt.sony_crc32(bt.FEATURE_CRC_SEED, patched[:-4])
        assert patched[-4:] == expected.to_bytes(4, "little")

    def test_preserves_length(self):
        original = self._fake_report9()
        assert len(bt.patch_report9_mac(original)) == len(original)

    def test_short_input_returned_untouched(self):
        assert bt.patch_report9_mac(b"\x09\x11") == b"\x09\x11"


class TestReportConstants:
    def test_default_output_report_shape(self):
        # 0x31 BT output report: 1 id + 1 seq + 1 tag + 71 payload + 4 CRC
        assert len(bt.DEFAULT_OUTPUT_REPORT) == 78
        assert bt.DEFAULT_OUTPUT_REPORT[0] == 0x31

    def test_trigger_fields_are_adjacent_11_byte_groups(self):
        r, l = bt.RIGHT_TRIGGER_FIELD, bt.LEFT_TRIGGER_FIELD
        assert r.stop - r.start == 11
        assert l.stop - l.start == 11
        assert r.stop == l.start

    def test_lightbar_rgb_is_3_bytes(self):
        f = bt.LIGHTBAR_RGB_FIELD
        assert f.stop - f.start == 3
