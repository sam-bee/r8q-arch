# Battery helper fixtures

`test_r8q_battery.py` executes a temporary path-rewritten copy of the tracked
`r8q-battery-up.sh` against synthetic `/etc`, `/proc`, `/sys`, and private
payload trees. It uses fake `systemctl`, `findmnt`, `insmod`, `modinfo`, and
hash commands, so it never reads host sysfs, loads a host module, or contacts a
phone.

The fixtures require failure before `insmod` for wrong kernel/identity, an
inactive route, a USB configuration timeout, a pre-existing MAX module, and a
module hash mismatch. A success fixture records and checks the required
fuel-gauge → MFD → charger order plus telemetry/default-current checks.

Run from `r8q-arch/`:

```sh
python3 -B tests/r8q-battery/test_r8q_battery.py
```
