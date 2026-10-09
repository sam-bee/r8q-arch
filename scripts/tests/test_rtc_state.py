#!/usr/bin/env python3
"""Corruption tests for the production r8q RTC state codec.

The shell validator is extracted from the installed production helper and run
in a private temporary directory.  These tests deliberately do not execute
the helper's root, mount, lock, driver, bind, or unbind paths.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "rootfs/usr/local/sbin/r8q-rtc-state"
FUNCTIONS = ("die", "file_size_at_most", "validate_payload", "validate_state")


def extract_function(source: str, name: str) -> str:
    """Return one complete top-level shell function from the helper source."""

    lines = source.splitlines(keepends=True)
    start = next(
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"{re.escape(name)}\(\)\s*\n?", line)
    )
    end = next(
        index
        for index in range(start + 1, len(lines))
        if lines[index].strip() == "}"
    )
    return "".join(lines[start : end + 1])


def state_bytes(payload: bytes) -> bytes:
    return hashlib.sha256(payload).hexdigest().encode("ascii") + b"\n" + payload


def rtc_payload(*, attributes: bytes = b"\x07\x00\x00\x00", reserved: bytes = b"\0" * 8) -> bytes:
    gps_offset = (0x12345678).to_bytes(4, "little")
    return attributes + gps_offset + reserved


class RTCStateCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.helper_source = HELPER.read_text(encoding="utf-8")
        cls.function_source = "\n".join(
            extract_function(cls.helper_source, name) for name in FUNCTIONS
        )

    def run_validator(self, state_path: Path, tempdir: Path) -> subprocess.CompletedProcess[bytes]:
        isolated_prefix = str(tempdir)
        extracted = self.function_source.replace(
            "/run/r8q-rtc", isolated_prefix + "/r8q-rtc"
        )
        harness = "\n".join(
            (
                "#!/bin/sh",
                "set -eu",
                "PATH=/usr/bin:/usr/sbin:/bin:/sbin",
                "export PATH",
                "TMP_STATE_HEAD=",
                "TMP_PAYLOAD=",
                extracted,
                'validate_state "$1"',
            )
        )
        return subprocess.run(
            ["sh", "-c", harness, "r8q-rtc-codec-test", str(state_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_valid_81_byte_fixture_is_accepted(self) -> None:
        payload = rtc_payload()
        encoded = state_bytes(payload)
        self.assertEqual(len(payload), 16)
        self.assertEqual(len(encoded), 81)

        with tempfile.TemporaryDirectory(prefix="r8q-rtc-codec-") as directory:
            tempdir = Path(directory)
            state_path = tempdir / "rtcinfo.state"
            state_path.write_bytes(encoded)
            result = self.run_validator(state_path, tempdir)

        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_corrupt_fixtures_are_rejected(self) -> None:
        valid_payload = rtc_payload()
        valid_state = state_bytes(valid_payload)
        cases = {
            "truncation": valid_state[:-1],
            "trailing": valid_state + b"\0",
            "bad_checksum": b"0" * 64 + valid_state[64:],
            "attrs_not_7": state_bytes(rtc_payload(attributes=b"\x06\0\0\0")),
            "reserved_nonzero": state_bytes(rtc_payload(reserved=b"\0" * 7 + b"\x01")),
            "wrong_newline": valid_state[:64] + b"X" + valid_state[65:],
        }

        for name, fixture in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(
                prefix="r8q-rtc-codec-"
            ) as directory:
                tempdir = Path(directory)
                state_path = tempdir / "rtcinfo.state"
                state_path.write_bytes(fixture)
                result = self.run_validator(state_path, tempdir)
                self.assertNotEqual(result.returncode, 0, result.stderr.decode())

    def test_symlink_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r8q-rtc-codec-") as directory:
            tempdir = Path(directory)
            target = tempdir / "valid-state"
            state_path = tempdir / "rtcinfo.state"
            target.write_bytes(state_bytes(rtc_payload()))
            state_path.symlink_to(target)
            result = self.run_validator(state_path, tempdir)

        self.assertNotEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
