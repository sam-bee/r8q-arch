#!/usr/bin/env python3
"""Validate and stage the r8q mainline DTB for a Mu-Silicium build.

This helper deliberately edits only the r8q FDF device-tree block and the
Mu-Silicium FdtBlob input. Resources/DTBs/r8q.dtb is the Android bootstrap DTB
consumed by build_uefi.py and is never a destination here.
"""

from __future__ import annotations

import argparse
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path


FDT_MAGIC = 0xD00DFEED
FDT_HEADER_SIZE = 40
DEVICE_TREE_GUID = "25462CDA-221F-47DF-AC1D-259CFAA4E326"
FDT_DESTINATION = Path("Platforms/Samsung/r8qPkg/FdtBlob/sm8250-samsung-r8q.dtb")
FDF_PATH = Path("Platforms/Samsung/r8qPkg/r8q.fdf")

COMMENTED_DEVICE_TREE_BLOCK = (
    "  #INF EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.inf",
    f"  #FILE FREEFORM = {DEVICE_TREE_GUID} {{",
    "  #  SECTION RAW = r8qPkg/FdtBlob/sm8250-samsung-r8q.dtb",
    '  #  SECTION UI = "Device Tree"',
    "  #}",
)

ACTIVE_DEVICE_TREE_BLOCK = (
    "  INF EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.inf",
    f"  FILE FREEFORM = {DEVICE_TREE_GUID} {{",
    "    SECTION RAW = r8qPkg/FdtBlob/sm8250-samsung-r8q.dtb",
    '    SECTION UI = "Device Tree"',
    "  }",
)


class PrepareError(RuntimeError):
    """A required input or exact expected Mu-Silicium state was invalid."""


@dataclass(frozen=True)
class PreparationResult:
    fdf_changed: bool
    destination: Path
    dtb_size: int


def _line_blocks(lines: list[str], block: tuple[str, ...]) -> list[int]:
    width = len(block)
    return [
        index
        for index in range(len(lines) - width + 1)
        if tuple(lines[index : index + width]) == block
    ]


def _read_fdf(path: Path) -> tuple[list[str], str, bool]:
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise PrepareError(f"cannot read FDF {path}: {exc}") from exc
    except UnicodeError as exc:
        raise PrepareError(f"FDF is not UTF-8: {path}") from exc

    if "\r" in text.replace("\r\n", ""):
        raise PrepareError(f"FDF has unexpected carriage returns: {path}")
    if "\r\n" in text and "\n" in text.replace("\r\n", ""):
        raise PrepareError(f"FDF has mixed line endings: {path}")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(), newline, text.endswith(("\n", "\r"))


def _write_text_atomically(path: Path, text: str) -> None:
    if path.is_symlink():
        raise PrepareError(f"refusing symlinked FDF destination: {path}")
    temporary: Path | None = None
    try:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise PrepareError(f"cannot update {path}: {exc}") from exc


def activate_fdf(path: Path) -> bool:
    """Activate the one exact commented block, or verify it is already active."""

    if path.is_symlink():
        raise PrepareError(f"refusing symlinked FDF: {path}")
    lines, newline, had_final_newline = _read_fdf(path)
    commented = _line_blocks(lines, COMMENTED_DEVICE_TREE_BLOCK)
    active = _line_blocks(lines, ACTIVE_DEVICE_TREE_BLOCK)

    references = (
        DEVICE_TREE_GUID,
        "EmbeddedPkg/Drivers/DtPlatformDxe/DtPlatformDxe.inf",
        "r8qPkg/FdtBlob/sm8250-samsung-r8q.dtb",
    )
    if len(commented) + len(active) != 1 or any(
        sum(line.count(reference) for line in lines) != 1
        for reference in references
    ):
        raise PrepareError(
            "r8q.fdf does not contain exactly one expected commented or active "
            "device-tree block; refusing unexpected content"
        )
    if active:
        return False

    index = commented[0]
    updated = lines[:index] + list(ACTIVE_DEVICE_TREE_BLOCK) + lines[index + len(COMMENTED_DEVICE_TREE_BLOCK) :]
    text = newline.join(updated)
    if had_final_newline:
        text += newline
    _write_text_atomically(path, text)
    return True


def validate_dtb(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PrepareError(f"cannot read mainline DTB {path}: {exc}") from exc
    if len(data) < 8:
        raise PrepareError(f"mainline DTB is too short: {path}")

    magic, total_size = struct.unpack_from(">II", data)
    if magic != FDT_MAGIC:
        raise PrepareError(f"mainline DTB has bad FDT magic 0x{magic:08x}: {path}")
    if total_size < FDT_HEADER_SIZE:
        raise PrepareError(f"mainline DTB total_size is below the FDT header: {total_size}")
    if total_size > len(data):
        raise PrepareError(
            f"mainline DTB total_size {total_size} exceeds file size {len(data)}: {path}"
        )
    if total_size != len(data):
        raise PrepareError(
            f"mainline DTB total_size {total_size} does not match file size {len(data)}: {path}"
        )
    return data


def _check_destination_components(root: Path, destination: Path) -> None:
    if root.is_symlink():
        raise PrepareError(f"refusing symlinked Mu-Silicium root: {root}")
    if not root.is_dir():
        raise PrepareError(f"Mu-Silicium root is not a directory: {root}")
    try:
        relative = destination.relative_to(root)
    except ValueError as exc:
        raise PrepareError(f"DTB destination escapes Mu-Silicium root: {destination}") from exc

    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PrepareError(f"refusing symlinked DTB destination component: {current}")


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise PrepareError(f"refusing symlinked DTB destination: {path}")
    temporary: Path | None = None
    try:
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise PrepareError(f"cannot update {path}: {exc}") from exc


def install_dtb(dtb_data: bytes, musil: Path) -> Path:
    destination = musil / FDT_DESTINATION
    _check_destination_components(musil, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _check_destination_components(musil, destination)
    _write_bytes_atomically(destination, dtb_data)
    return destination


def prepare_uefi_inputs(musil: Path, dtb: Path) -> PreparationResult:
    musil = Path(musil)
    data = validate_dtb(Path(dtb))
    fdf_path = musil / FDF_PATH
    destination = musil / FDT_DESTINATION
    _check_destination_components(musil, fdf_path)
    _check_destination_components(musil, destination)
    fdf_changed = activate_fdf(fdf_path)
    destination = install_dtb(data, musil)
    return PreparationResult(fdf_changed, destination, len(data))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--musil", required=True, type=Path, help="Mu-Silicium checkout")
    parser.add_argument("--dtb", required=True, type=Path, help="mainline Linux DTB")
    args = parser.parse_args(argv)
    try:
        result = prepare_uefi_inputs(args.musil, args.dtb)
    except PrepareError as exc:
        parser.error(str(exc))
    state = "activated" if result.fdf_changed else "already active"
    print(f"[uefi-prep] FDF device-tree block: {state}")
    print(f"[uefi-prep] staged {result.dtb_size} DTB bytes at {result.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
