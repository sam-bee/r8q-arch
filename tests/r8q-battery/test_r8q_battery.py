#!/usr/bin/env python3
"""Offline fixture checks for the route-gated battery helper.

A temporary path-rewritten copy is used because the production helper has
fixed target paths by design. The shell control flow and guard ordering are
unchanged. Fake commands and synthetic sysfs/proc trees never touch host
sysfs, load modules, or contact the phone.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "rootfs/usr/local/sbin/r8q-battery-up.sh"
SERVICE = REPO_ROOT / "rootfs/etc/systemd/system/r8q-battery.service"
KERNEL = "7.1.2-r8q-rtc2"
MACHINE_ID = "1290f2212bd743569044571db21a6c96"
ROOT_UUID = "217b9308-40c7-4eb0-90a9-09ed4e233173"
VERMAGIC = "7.1.2-r8q-rtc2 SMP preempt mod_unload aarch64"
MODULE_HASHES = {
    "max17042_battery.ko": "dab402c9a954140ba1fb9d4ee7cc5b0ba4fdd710ceef6f3e690b81b8d7e3d0e0",
    "max77705.ko": "d762ba600f60aeb861ba9bb74c963213db19eb4db9f928ef8538a1c27472a072",
    "max77705_charger.ko": "724ce35de17beb52dbec938a695b01a9e2e0ee757a4c864ae05b8f59e3cca593",
}


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def make_fixture(root: Path, *, usb_configured: bool = True, max_module: bool = False) -> None:
    sysfs = root / "sys"
    proc = root / "proc"
    etc = root / "etc"
    payload = root / "usr/local/lib/r8q-battery/7.1.2-r8q-rtc2"
    fake_bin = root / "bin"
    fake_bin.mkdir(parents=True)
    (root / "fakecmd.py").write_text(FAKE_COMMAND, encoding="utf-8")
    (root / "fakecmd.py").chmod(0o755)
    for name in ("id", "uname", "findmnt", "sleep", "systemctl", "sha256sum", "modinfo", "insmod"):
        (fake_bin / name).symlink_to(root / "fakecmd.py")

    for address in ("0036", "0066", "0069"):
        (sysfs / "bus/i2c/devices" / f"0-{address}").mkdir(parents=True)
    (sysfs / "bus/i2c/drivers/simple-mfd-i2c").mkdir(parents=True)
    (sysfs / "bus/i2c/devices/0-0036/driver").symlink_to(
        sysfs / "bus/i2c/drivers/simple-mfd-i2c"
    )
    if usb_configured:
        write(sysfs / "class/udc/fixture-udc/state", "configured\n")
        write(sysfs / "class/net/usb0/operstate", "up\n")

    modules = "i2c_core 32768 0 - Live 0x0\n"
    if max_module:
        modules += "max77705 123 0 - Live 0x0\n"
    write(proc / "modules", modules)
    write(etc / "machine-id", MACHINE_ID + "\n")
    write(
        etc / "r8q-usb-route.env",
        f"EXPECTED_KERNEL={KERNEL}\n"
        f"EXPECTED_MACHINE_ID={MACHINE_ID}\n"
        f"EXPECTED_ROOT_UUID={ROOT_UUID}\n",
    )
    for name in MODULE_HASHES:
        write(payload / name, "fixture module\n")


FAKE_COMMAND = r'''#!/usr/bin/python3
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
root = Path(os.environ["R8Q_FIXTURE"])
case = os.environ.get("R8Q_CASE", "")
args = sys.argv[1:]

if name == "id":
    print("0")
elif name == "uname":
    print(os.environ.get("R8Q_FAKE_KERNEL", "7.1.2-r8q-rtc2"))
elif name == "findmnt":
    print(os.environ.get("R8Q_FAKE_ROOT_UUID", "217b9308-40c7-4eb0-90a9-09ed4e233173"))
elif name == "sleep":
    pass
elif name == "systemctl":
    joined = " ".join(args)
    if "r8q-usb-route.service" in joined and case == "routeinactive" and "ActiveState" in joined:
        print("inactive")
    elif "ActiveState" in joined:
        print("active")
    elif "Result" in joined:
        print("success")
elif name == "sha256sum":
    if case == "modulehash":
        digest = "0" * 64
    else:
        digest = next(
            value for suffix, value in {
                "max17042_battery.ko": "dab402c9a954140ba1fb9d4ee7cc5b0ba4fdd710ceef6f3e690b81b8d7e3d0e0",
                "max77705.ko": "d762ba600f60aeb861ba9bb74c963213db19eb4db9f928ef8538a1c27472a072",
                "max77705_charger.ko": "724ce35de17beb52dbec938a695b01a9e2e0ee757a4c864ae05b8f59e3cca593",
            }.items()
            if suffix in args[0]
        )
    print(f"{digest}  {args[0]}")
elif name == "modinfo":
    print("7.1.2-r8q-rtc2 SMP preempt mod_unload aarch64")
elif name == "insmod":
    module = Path(args[0]).name
    with (root / "insmod.log").open("a", encoding="utf-8") as stream:
        stream.write(module + "\n")
    proc = root / "proc/modules"
    if module == "max17042_battery.ko":
        proc.write_text(proc.read_text() + "max17042_battery 123 0 - Live 0x0\n")
        base = root / "sys/class/power_supply/max170xx_battery"
        for name, value in {
            "health": "Good\n", "present": "1\n", "capacity": "70\n",
            "voltage_now": "3900000\n", "temp": "240\n",
        }.items():
            write_path = base / name
            write_path.parent.mkdir(parents=True, exist_ok=True)
            write_path.write_text(value)
    elif module == "max77705.ko":
        proc.write_text(proc.read_text() + "max77705 123 0 - Live 0x0\n")
        driver = root / "sys/bus/i2c/drivers/max77705"
        driver.mkdir(parents=True, exist_ok=True)
        (root / "sys/bus/i2c/devices/0-0066/driver").symlink_to(driver)
    elif module == "max77705_charger.ko":
        proc.write_text(proc.read_text() + "max77705_charger 123 0 - Live 0x0\n")
        driver = root / "sys/bus/i2c/drivers/max77705-charger"
        driver.mkdir(parents=True, exist_ok=True)
        (root / "sys/bus/i2c/devices/0-0069/driver").symlink_to(driver)
        base = root / "sys/class/power_supply/max77705-charger"
        for name, value in {
            "health": "Good\n", "online": "1\n",
            "input_current_limit": "500000\n",
            "constant_charge_current": "500000\n",
        }.items():
            write_path = base / name
            write_path.parent.mkdir(parents=True, exist_ok=True)
            write_path.write_text(value)
    else:
        raise SystemExit(1)
else:
    raise SystemExit(f"unexpected fake command: {name}")
'''


def materialize_helper(root: Path) -> Path:
    text = HELPER.read_text(encoding="utf-8")
    for old, new in (
        ("/usr/local/lib/r8q-battery", str(root / "usr/local/lib/r8q-battery")),
        ("/var/lib/r8q-battery", str(root / "var/lib/r8q-battery")),
        ("/etc/", str(root / "etc") + "/"),
        ("/sys/", str(root / "sys") + "/"),
        ("/proc/", str(root / "proc") + "/"),
    ):
        text = text.replace(old, new)
    text = text.replace(
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        f"PATH={root / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
    )
    helper = root / "helper.sh"
    write(helper, text)
    helper.chmod(0o755)
    return helper


def run_case(
    root: Path,
    name: str,
    *,
    usb_configured: bool = True,
    max_module: bool = False,
    wrong_machine: bool = False,
    wrong_root_uuid: bool = False,
    wrong_kernel: bool = False,
) -> subprocess.CompletedProcess[str]:
    make_fixture(root, usb_configured=usb_configured, max_module=max_module)
    if wrong_machine:
        write(root / "etc/machine-id", "wrong-machine-id\n")
    helper = materialize_helper(root)
    env = os.environ.copy()
    env.update(
        {
            "R8Q_FIXTURE": str(root),
            "R8Q_INSMOD_LOG": str(root / "insmod.log"),
            "R8Q_CASE": name,
            "PATH": f"{root / 'bin'}:{env['PATH']}",
        }
    )
    if wrong_kernel:
        env["R8Q_FAKE_KERNEL"] = "wrong-kernel"
    if wrong_root_uuid:
        env["R8Q_FAKE_ROOT_UUID"] = "wrong-root-uuid"
    return subprocess.run(
        [str(helper)], env=env, text=True, capture_output=True, timeout=5
    )


def assert_rejected(root: Path, name: str, expected: str, **kwargs: object) -> None:
    result = run_case(root, name, **kwargs)
    assert result.returncode != 0, (
        f"{name} unexpectedly passed:\n{result.stdout}\n{result.stderr}"
    )
    assert expected in result.stderr, f"{name}: missing {expected!r}: {result.stderr}"
    assert not (root / "insmod.log").exists(), f"{name} reached insmod"


def main() -> int:
    service = SERVICE.read_text(encoding="utf-8")
    assert "Requires=r8q-usb-gadget.service r8q-usb-route.service r8q-touch.service" in service
    assert "After=r8q-usb-gadget.service r8q-usb-route.service r8q-touch.service" in service
    assert "ExecStart=/usr/local/sbin/r8q-battery-up.sh" in service
    assert "ExecStartPost" not in service
    assert "700000" not in service and "1000000" not in service

    with tempfile.TemporaryDirectory(prefix="r8q-battery-fixture-") as temp:
        base = Path(temp)
        assert_rejected(
            base / "wrong-kernel", "wrongkernel", "unexpected kernel", wrong_kernel=True
        )
        assert_rejected(
            base / "wrong-identity", "identity", "unexpected machine-id",
            wrong_machine=True,
        )
        assert_rejected(
            base / "wrong-root-uuid", "rootuuid", "unexpected root UUID",
            wrong_root_uuid=True,
        )
        assert_rejected(
            base / "route-inactive", "routeinactive",
            "r8q-usb-route.service is not active",
        )
        assert_rejected(
            base / "usb-timeout", "usbtimeout",
            "did not become configured", usb_configured=False,
        )
        assert_rejected(
            base / "max-module", "maxmodule",
            "MAX module is already loaded", max_module=True,
        )
        assert_rejected(
            base / "module-hash", "modulehash",
            "hash mismatch for",
        )

        success_root = base / "success"
        result = run_case(success_root, "success")
        assert result.returncode == 0, (
            f"success fixture failed:\n{result.stdout}\n{result.stderr}"
        )
        assert (success_root / "insmod.log").read_text(
            encoding="utf-8"
        ).splitlines() == [
            "max17042_battery.ko",
            "max77705.ko",
            "max77705_charger.ko",
        ]
        assert "fuel_stage=pass" in result.stdout
        assert "mfd_stage=pass" in result.stdout
        assert "charger_stage=pass" in result.stdout

    print("PASS: battery identity, route, USB, module-conflict, hash, and ordered-load fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
