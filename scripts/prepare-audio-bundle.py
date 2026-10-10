#!/usr/bin/env python3
"""Pack the reviewed exact RTC2 audio module closure.

The input module directory is a private root containing only the 36 reviewed
relative module paths (the paths in PRIVATE_ROWS). Templates are copied from a
separate reviewed directory. The packager deliberately has no repository or
historical staging path defaults: callers choose all three directories.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

RELEASE = "7.1.2-r8q-rtc2"
VERMAGIC = "7.1.2-r8q-rtc2 SMP preempt mod_unload aarch64"
MODULE_COUNT = 36
TEMPLATE_NAMES = ("load-r8q-audio.sh", "init-r8q-audio.sh", "r8q-audio-start.service")
ARCHIVE_NAME = "r8q-audio-7.1.2-r8q-rtc2.tar.gz"
PRIVATE_ROWS = [
    ('01', 'qrtr', '854041a5e376b6b1cf3fa19cae4e723f26ed7f788422f9a7ad8378b52d7502ad', 'net/qrtr/qrtr.ko', 'Exact RTC2 QRTR provider required by qrtr_smd'),
    ('02', 'qrtr_smd', '6408e0852dc8739ca2a638d7b7ec296970621460d85c552c5814c7673862a2be', 'qrtr-smd.ko', 'Binds the ADSP IPCRTR RPMSG channel'),
    ('03', 'qmi_helpers', '90dc062fb00cf6b7767d62bc8d7d4819d4f5550eb3849c8f1dac515a3b5412e7', 'qmi_helpers.ko', 'QMI base for PDR and PD mapping'),
    ('04', 'qcom_pdr_msg', 'c80db376e4bc3c1d2564c59559ab94f3b93753a5fc6f072aa74a94c4a54a9f50', 'qcom_pdr_msg.ko', 'PDR message transport'),
    ('05', 'pdr_interface', '84b3a14933a51556da4f6a42c68de9aec2bfad279afc73db7c8c14b7c51b45ea', 'pdr_interface.ko', 'APR/PDR service discovery'),
    ('06', 'apr', '3f19bf46323b947de1623831e79c0e79949cb50c743637285c439110d2336723', 'apr.ko', 'APR bus before Q6 services'),
    ('07', 'qcom_glink_smem', '352361c4250976077247d752c935ec29dddb489a0f64740c0cf23ae5cb9849a0', 'qcom_glink_smem.ko', 'GLINK-SMEM transport'),
    ('08', 'qcom_common', 'fa946f70110aafe8f2f3113498c3a2a72dad1587820f34fe3e936c99186894b4', 'qcom_common.ko', 'Common QCOM remoteproc support'),
    ('09', 'qcom_pd_mapper', 'bc952ebd73423b434851d81344fe6d2b6baa0a036c6f012e5119789b221a0ddf', 'qcom_pd_mapper.ko', 'Maps the ADSP audio power domain after qcom_common'),
    ('10', 'qcom_pil_info', '183bbb1378aeb7c7de2bfd53ceb3283e73ca43eac9cd904f6bd8a50baf7b16bf', 'qcom_pil_info.ko', 'PAS helper'),
    ('11', 'mdt_loader', '9fdeaa07bf30041112cc2bfba05c09c1d2b6559f24ae4516132510d018e54f05', 'mdt_loader.ko', 'ADSP firmware segment loader'),
    ('12', 'qcom_sysmon', '49c522f8c320922253a681cab97bc0e459662bb31256d8ab43c408cde67f9b0e', 'qcom_sysmon.ko', 'Q6V5 system monitor'),
    ('13', 'qcom_q6v5', '269da4a08a2d51eea1b60042a9af8f1b2cd7271cd51468685ccc0d64b8fee1ef', 'qcom_q6v5.ko', 'Q6V5 common library'),
    ('14', 'qcom_q6v5_pas', 'bbe5a5e019f0f71e62db8b674e6f1ee77377dc27060774559a4b21afe1451abf', 'qcom_q6v5_pas.ko', 'Auto-boots the exact ADSP PAS node'),
    ('15', 'soundcore', '5d6044fcfef5e11349cd16d2e4f9a602e3029a2850ddae3cea96f4dcfe94354b', 'soundcore.ko', 'ALSA base'),
    ('16', 'snd', '63b7c5ec4381e1a9ff9e622148c1a59097e5c7d00cf9d19ec5d002fc59b6e447', 'snd.ko', 'ALSA core'),
    ('17', 'snd_timer', '169158c968ded0279be714c9ad61690b823464e1cf6a793e55a1a2934e473730', 'snd-timer.ko', 'PCM timing dependency'),
    ('18', 'snd_pcm', '48ec6053bbe17327b65aa61c718de33689c9406b8e3582ce42bec2c786e3ad8a', 'snd-pcm.ko', 'PCM dependency'),
    ('19', 'snd_compress', '0687606a1e94dd9a9c18d6f46cfcd981376d9cd1868765a5c6e0f9c68a525601', 'snd-compress.ko', 'WM ADSP and CS35L41 dependency'),
    ('20', 'snd_pcm_dmaengine', 'ea3124a25f97b301a487e54756ea1378b7683fccd355ebe3ae18cb45bbd6fb9a', 'snd-pcm-dmaengine.ko', 'ASoC DMA helper'),
    ('21', 'snd_soc_core', '8afc004e2b73ba933d7648e4c180cd0dc3a6af9653b6ed58c5430ed60a4d12af', 'snd-soc-core.ko', 'ASoC core'),
    ('22', 'snd_soc_qcom_common', '0a9b228a2921ca212d759cfabbdf762ac7fbada041e15aed01bcbeb9bd38f1e7', 'snd-soc-qcom-common.ko', 'QCOM machine/card helper'),
    ('23', 'snd_q6dsp_common', '26ad1c428824945d8e7848b1cd987622c2aa261c9ef83fe537fac494fcc7ce2b', 'snd-q6dsp-common.ko', 'QDSP6 common helpers'),
    ('24', 'q6core', '2379bb9a1da5fa1a0cdc69d9934c47caf1c8594fb282636aa6d1d9902a74bb08', 'q6core.ko', 'Q6 core APR service'),
    ('25', 'q6afe', '8e28964b283dc96bb9b983016508f83a710b060978e6bcb90accbf35fd9ffd5e', 'q6afe.ko', 'Matched v8 Q6AFE wire controls; validated with CPU offset pair'),
    ('26', 'q6afe_dai', '0465102a927a2d1a066044357ff41293c6a7fa1e8f8960b4a7b46ed282cad67a', 'q6afe-dai.ko', 'Matched v8 Q6AFE DAI companion; carries data-delay and TDM controls'),
    ('27', 'q6adm', '574fb9c93efdd91f26ac97650a95cfe37773dd8c728f3601c15f94e51168e93f', 'q6adm.ko', 'Q6 ADM service'),
    ('28', 'q6routing', '20f5cba815856be6a9cbecffd7fd003a7422a8cf0307b8f9a0233cbd6bb62635', 'q6routing.ko', 'Q6 routing DAI provider'),
    ('29', 'q6asm', '0b32e86fd16343f22a244d322f2e9d6b0f308ea81bc86709ff05db3828b92a5a', 'q6asm.ko', 'Q6 ASM service'),
    ('30', 'q6asm_dai', 'c34fd6a54af4d6ac82635e4702f068d3a9bda4deb2fef5b59005cdde03e8d5f7', 'q6asm-dai.ko', 'Multimedia1 DAI provider'),
    ('31', 'cs_dsp', 'd639e25adcd68b88542d790c771ed13c120d3a1156bb440da29d0ae0b8cfba7c', 'cs_dsp.ko', 'Frozen v10 Cirrus DSP common library'),
    ('32', 'snd_soc_wm_adsp', '5959f00ae86fb8cf455e2c72d68b9cbf1dc7cefcfa57f940e2f0e145f12470fa', 'snd-soc-wm-adsp.ko', 'Frozen v10 Cirrus WM ADSP support'),
    ('33', 'snd_soc_cs35l41_lib', '851f01d2af0da82db515a8154f0401855e8f63daab25f47b0315983ce935394e', 'snd-soc-cs35l41-lib.ko', 'Frozen v10 CS35L41 common library'),
    ('34', 'snd_soc_cs35l41', 'd7962eab2a03a069d56acbf50a2095404f71b9e3f5a8d4600e05250f727ee5a0', 'snd-soc-cs35l41.ko', 'Frozen v10 CS35L41 codec core; RESUME-ACK latch hardware validated'),
    ('35', 'snd_soc_cs35l41_i2c', '21a456ae6f48db1f45e7a2a8477ec9858563c525dbed525455ce882157bc247f', 'snd-soc-cs35l41-i2c.ko', 'Frozen v10 I2C11 codec transport; RESUME-ACK latch hardware validated'),
    ('36', 'r8q_cs35l41_card', 'f7defab38b6b2a400369c62c73e57ebb6313de4d46371989747d55d4f060fef6', 'r8q-cs35l41-card.ko', 'v10 card with Q6AFE CPU channel-map offset {0,4}; paired PCM hardware validated'),
]
TABLE_HEADER = ("order", "module", "source_artifact", "sha256", "private_artifact", "why")


def die(message: str) -> None:
    raise SystemExit(f"prepare-audio-bundle: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file() or path.is_symlink():
        die(f"{label} is not a regular non-symlink file: {path}")


def run_modinfo(modinfo: str, field: str, path: Path) -> str:
    try:
        result = subprocess.run(
            [modinfo, "-F", field, str(path)],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        die(f"modinfo {field} failed for {path}: {detail.strip()}")
    return result.stdout.strip()


def validate_rows(modules: Path, modinfo: str) -> list[dict[str, str]]:
    if len(PRIVATE_ROWS) != MODULE_COUNT:
        die(f"internal row count is {len(PRIVATE_ROWS)}, expected {MODULE_COUNT}")
    names = {row[1] for row in PRIVATE_ROWS}
    if len(names) != MODULE_COUNT:
        die("reviewed module names are not unique")
    result: list[dict[str, str]] = []
    for expected_order, name, expected_hash, private, why in PRIVATE_ROWS:
        relative = Path(private)
        if relative.is_absolute() or ".." in relative.parts:
            die(f"unsafe private module path: {private}")
        path = modules / relative
        regular(path, f"module {name}")
        actual_hash = sha256(path)
        if actual_hash != expected_hash:
            die(f"hash mismatch for {private}: {actual_hash} != {expected_hash}")
        actual_name = run_modinfo(modinfo, "name", path)
        if actual_name != name:
            die(f"module name mismatch for {private}: {actual_name} != {name}")
        actual_vermagic = run_modinfo(modinfo, "vermagic", path)
        if actual_vermagic != VERMAGIC:
            die(f"vermagic mismatch for {private}: {actual_vermagic!r}")
        result.append({
            "order": expected_order,
            "module": name,
            "source_artifact": private,
            "sha256": actual_hash,
            "private_artifact": private,
            "why": why,
            "depends": run_modinfo(modinfo, "depends", path),
        })
    for row in result:
        dependencies = [item.replace("-", "_") for item in row["depends"].split(",") if item]
        missing = [item for item in dependencies if item not in names]
        if missing:
            die(f"{row['module']} imports modules outside the reviewed closure: {','.join(missing)}")
    return result


def validate_service(text: str) -> None:
    section = None
    values: dict[tuple[str, str], str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" in line and section is not None:
            key, value = line.split("=", 1)
            values[(section, key)] = value
    if values.get(("Service", "Type")) != "oneshot":
        die("service must be Type=oneshot in [Service]")
    if values.get(("Service", "RemainAfterExit")) != "yes":
        die("service must retain successful state in [Service]")
    if values.get(("Service", "TimeoutStartSec")) != "120":
        die("service must set TimeoutStartSec=120 inside [Service]")
    if values.get(("Service", "ExecStart")) != f"/opt/r8q-audio/{RELEASE}/load-r8q-audio.sh":
        die("service ExecStart does not target the fixed RTC2 loader")
    if values.get(("Service", "ExecStartPost")) != f"/opt/r8q-audio/{RELEASE}/init-r8q-audio.sh":
        die("service ExecStartPost does not target the fixed RTC2 init")


def copy_templates(templates: Path, output: Path) -> None:
    for name in TEMPLATE_NAMES:
        source = templates / name
        regular(source, f"template {name}")
        if name.endswith(".service"):
            validate_service(source.read_text())
        elif name == "load-r8q-audio.sh":
            if "EXPECTED_RELEASE=7.1.2-r8q-rtc2" not in source.read_text():
                die("loader template does not pin the RTC2 release")
        elif name == "init-r8q-audio.sh":
            if "7.1.2-r8q-rtc2" not in source.read_text():
                die("init template does not pin the RTC2 release")
        shutil.copy2(source, output / name)


def write_table(output: Path, rows: list[dict[str, str]]) -> None:
    with (output / "module-load-order.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(TABLE_HEADER)
        for row in rows:
            writer.writerow(tuple(row[key] for key in TABLE_HEADER))
    with (output / "module-hashes.sha256").open("w") as stream:
        for row in rows:
            stream.write(f"{row['sha256']}  {row['private_artifact']}\n")


def write_manifest(output: Path) -> str:
    paths = sorted(
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "package-manifest.sha256" and path.name != ARCHIVE_NAME
    )
    manifest = output / "package-manifest.sha256"
    with manifest.open("w") as stream:
        for relative in paths:
            stream.write(f"{sha256(output / relative)}  {relative}\n")
    return sha256(manifest)


def archive(output: Path) -> str:
    target = output / ARCHIVE_NAME
    with target.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as tar:
                directory = tarfile.TarInfo(".")
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                directory.mtime = 0
                directory.uid = directory.gid = 0
                directory.uname = directory.gname = ""
                tar.addfile(directory)
                for path in sorted(output.rglob("*")):
                    if not path.is_file() or path.name == ARCHIVE_NAME:
                        continue
                    relative = path.relative_to(output).as_posix()
                    data = path.read_bytes()
                    info = tarfile.TarInfo(relative)
                    info.size = len(data)
                    info.mode = stat.S_IMODE(path.stat().st_mode)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(data))
    return sha256(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules-directory", type=Path, required=True)
    parser.add_argument("--templates-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    modules = args.modules_directory.resolve()
    templates = args.templates_directory.resolve()
    output = args.output.resolve()
    if not modules.is_dir():
        die(f"modules directory is not a directory: {modules}")
    if not templates.is_dir():
        die(f"templates directory is not a directory: {templates}")
    if output.exists():
        die(f"output directory already exists; choose a new directory: {output}")
    if output == modules or output == templates:
        die("output must be distinct from both input directories")
    modinfo = shutil.which("modinfo") or "/usr/sbin/modinfo"
    if not Path(modinfo).exists():
        die("modinfo is required on the laptop; install nothing automatically")
    rows = validate_rows(modules, modinfo)
    output.mkdir(parents=True)
    try:
        copy_templates(templates, output)
        for row in rows:
            source = modules / row["private_artifact"]
            destination = output / row["private_artifact"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        write_table(output, rows)
        manifest_hash = write_manifest(output)
        archive_hash = archive(output)
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    print(f"modules={len(rows)}")
    print(f"release={RELEASE}")
    print(f"package_manifest_sha256={manifest_hash}")
    print(f"archive={output / ARCHIVE_NAME}")
    print(f"archive_sha256={archive_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
