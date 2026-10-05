#!/usr/bin/env python3
"""Isolated tests for scripts/prepare-uefi-dtb.py."""

from __future__ import annotations

import runpy
import struct
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/prepare-uefi-dtb.py"
MODULE = runpy.run_path(str(HELPER), run_name="uefi_prepare_test_module")
PrepareError = MODULE["PrepareError"]
FDT_HEADER_SIZE = MODULE["FDT_HEADER_SIZE"]
FDT_MAGIC = MODULE["FDT_MAGIC"]
FDF_PATH = MODULE["FDF_PATH"]
FDT_DESTINATION = MODULE["FDT_DESTINATION"]
COMMENTED = "\n".join(MODULE["COMMENTED_DEVICE_TREE_BLOCK"]) + "\n"
ACTIVE = "\n".join(MODULE["ACTIVE_DEVICE_TREE_BLOCK"]) + "\n"


def valid_dtb(total_size: int = FDT_HEADER_SIZE, extra: bytes = b"") -> bytes:
    body = struct.pack(">II", FDT_MAGIC, total_size) + bytes(max(0, total_size - 8))
    return body + extra


class PrepareUefiDtbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_musil(self, fdf_block: str) -> tuple[Path, Path, bytes]:
        temp = Path(self.tempdir.name)
        musil = temp / "Mu-Silicium"
        fdf = musil / FDF_PATH
        fdf.parent.mkdir(parents=True)
        fdf.write_text("[FV.FVMAIN]\n" + fdf_block + "\n!include QcomPkg/Extra.fdf.inc\n")
        bootstrap = b"android-bootstrap-dtb"
        bootstrap_path = musil / "Resources/DTBs/r8q.dtb"
        bootstrap_path.parent.mkdir(parents=True)
        bootstrap_path.write_bytes(bootstrap)
        return musil, fdf, bootstrap

    def test_commented_block_is_activated_and_bootstrap_is_unchanged(self) -> None:
        musil, fdf, bootstrap = self.make_musil(COMMENTED)
        mainline = Path(self.tempdir.name) / "mainline.dtb"
        mainline.write_bytes(valid_dtb())

        result = MODULE["prepare_uefi_inputs"](musil, mainline)

        self.assertTrue(result.fdf_changed)
        self.assertIn(ACTIVE, fdf.read_text())
        self.assertNotIn(COMMENTED, fdf.read_text())
        self.assertEqual((musil / "Resources/DTBs/r8q.dtb").read_bytes(), bootstrap)
        self.assertEqual((musil / FDT_DESTINATION).read_bytes(), mainline.read_bytes())
        self.assertEqual(result.dtb_size, len(mainline.read_bytes()))

    def test_already_active_block_is_idempotent(self) -> None:
        musil, fdf, _ = self.make_musil(ACTIVE)
        before = fdf.read_bytes()

        changed = MODULE["activate_fdf"](fdf)

        self.assertFalse(changed)
        self.assertEqual(fdf.read_bytes(), before)

    def test_unknown_fdf_content_is_rejected(self) -> None:
        unknown = COMMENTED.replace(
            "25462CDA-221F-47DF-AC1D-259CFAA4E326",
            "00000000-0000-0000-0000-000000000000",
        )
        _, fdf, _ = self.make_musil(unknown)

        with self.assertRaises(PrepareError):
            MODULE["activate_fdf"](fdf)

    def test_conflicting_partial_block_is_rejected(self) -> None:
        _, fdf, _ = self.make_musil(
            COMMENTED + '  FILE FREEFORM = 25462CDA-221F-47DF-AC1D-259CFAA4E326 {\n  }\n'
        )
        before = fdf.read_bytes()
        with self.assertRaises(PrepareError):
            MODULE["activate_fdf"](fdf)
        self.assertEqual(fdf.read_bytes(), before)

    def test_malformed_dtb_is_rejected(self) -> None:
        musil, _, _ = self.make_musil(ACTIVE)
        malformed = (
            b"not a DTB",
            valid_dtb(total_size=FDT_HEADER_SIZE - 1),
            struct.pack(">II", FDT_MAGIC, FDT_HEADER_SIZE + 100),
            valid_dtb(extra=b"trailing-data"),
        )
        for index, data in enumerate(malformed):
            dtb = Path(self.tempdir.name) / f"bad-{index}.dtb"
            dtb.write_bytes(data)
            with self.subTest(index=index), self.assertRaises(PrepareError):
                MODULE["prepare_uefi_inputs"](musil, dtb)

    def test_symlinked_destination_is_rejected(self) -> None:
        musil, _, _ = self.make_musil(ACTIVE)
        destination = musil / FDT_DESTINATION
        destination.parent.mkdir(parents=True, exist_ok=True)
        real_target = Path(self.tempdir.name) / "outside.dtb"
        real_target.write_bytes(b"outside")
        destination.symlink_to(real_target)

        with self.assertRaises(PrepareError):
            MODULE["install_dtb"](valid_dtb(), musil)

    def test_symlinked_destination_parent_is_rejected_before_fdf_change(self) -> None:
        musil, fdf, _ = self.make_musil(COMMENTED)
        before = fdf.read_bytes()
        outside = Path(self.tempdir.name) / "outside-dir"
        outside.mkdir()
        (musil / "Platforms/Samsung/r8qPkg/FdtBlob").symlink_to(
            outside, target_is_directory=True
        )
        mainline = Path(self.tempdir.name) / "mainline.dtb"
        mainline.write_bytes(valid_dtb())

        with self.assertRaises(PrepareError):
            MODULE["prepare_uefi_inputs"](musil, mainline)
        self.assertEqual(fdf.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
