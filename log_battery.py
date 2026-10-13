#!/usr/bin/env python3
"""
log_battery.py — append one row of battery telemetry to battery_log.csv

Run on a schedule (cron) to build a time series of:
  timestamp, cycle_count, design_capacity_mAh, max_capacity_mAh,
  current_capacity_mAh, health_pct, charge_pct, is_charging, power_source

Data source: `system_profiler SPPowerDataType -json`
This works on Apple Silicon (M1/M2/M3) Macs, including the M3 14" MBP.
"system_profiler" is slower but far more complete than `pmset`/`ioreg` for
capacity figures, and is what most third-party battery apps shell out to
under the hood. [Likely — based on common implementation pattern, not
something Apple documents]
"""

import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Data lives under ~/Library/Application Support, NOT ~/Documents: macOS TCC
# blocks background LaunchAgents from reading/writing ~/Documents, which
# silently killed the scheduled job after a reboot. This location is TCC-free
# for daemon contexts. See files/README.md for details.
CSV_PATH = Path.home() / "Library" / "Application Support" / "mac_battery" / "battery_log.csv"

FIELDS = [
    "timestamp",
    "cycle_count",
    "design_capacity_mAh",
    "max_capacity_mAh",
    "current_capacity_mAh",
    "health_pct",
    "charge_pct",
    "is_charging",
    "power_source",
    "temperature_c",
]


def get_power_data():
    """Pull raw battery JSON from system_profiler."""
    try:
        out = subprocess.run(
            ["system_profiler", "SPPowerDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"system_profiler failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("system_profiler timed out", file=sys.stderr)
        sys.exit(1)

    return json.loads(out.stdout)


def extract_row(data):
    """
    Map system_profiler's nested JSON to a flat row.
    Field names below match macOS Sonoma/Sequoia SPPowerDataType output as of
    2024-2025. [Likely — Apple has changed these keys across OS versions
    before, so this may need adjustment on future macOS releases]
    """
    power_items = data.get("SPPowerDataType", [])
    battery_info = {}
    for item in power_items:
        if "sppower_battery_charge_info" in item or "sppower_battery_health_info" in item:
            battery_info = item
            break

    if not battery_info:
        print("Could not find battery data in system_profiler output.", file=sys.stderr)
        sys.exit(1)

    charge_info = battery_info.get("sppower_battery_charge_info", {})
    health_info = battery_info.get("sppower_battery_health_info", {})

    cycle_count = health_info.get("sppower_battery_cycle_count")
    max_capacity_pct = health_info.get("sppower_battery_health_maximum_capacity")  # e.g. "87%"

    current_charge_pct = charge_info.get("sppower_battery_state_of_charge")  # e.g. 78 (int)
    is_charging = charge_info.get("sppower_battery_is_charging", False)
    ac_connected = charge_info.get("sppower_battery_is_connected", False)

    health_pct = None
    if isinstance(max_capacity_pct, str) and max_capacity_pct.endswith("%"):
        try:
            health_pct = float(max_capacity_pct.rstrip("%"))
        except ValueError:
            health_pct = None
    elif isinstance(max_capacity_pct, (int, float)):
        health_pct = float(max_capacity_pct)

    power_source = "AC" if ac_connected else "Battery"

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "cycle_count": cycle_count,
        "design_capacity_mAh": None,  # system_profiler doesn't expose raw mAh on Apple Silicon; see ioreg fallback below
        "max_capacity_mAh": None,
        "current_capacity_mAh": None,
        "health_pct": health_pct,
        "charge_pct": current_charge_pct,
        "is_charging": is_charging,
        "power_source": power_source,
        "temperature_c": None,
    }
    return row


def enrich_with_ioreg(row):
    """
    system_profiler doesn't report raw mAh capacities on Apple Silicon Macs.
    [Certain — confirmed pattern on M-series; Apple moved this data into
    IOPMPowerSource / AppleSmartBattery registry entries instead]
    Pull those from ioreg as a supplement. ioreg key names are undocumented
    and have shifted across macOS versions before, so this is best-effort:
    if parsing fails, the mAh fields just stay None and health_pct (from
    system_profiler) remains the reliable number.
    """
    try:
        out = subprocess.run(
            ["ioreg", "-rn", "AppleSmartBattery"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return row

    def grab(key):
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith(f'"{key}"'):
                try:
                    val = line.split("=", 1)[1].strip()
                    return int(val)
                except (IndexError, ValueError):
                    return None
        return None

    design = grab("DesignCapacity")
    max_cap = grab("AppleRawMaxCapacity") or grab("MaxCapacity")
    current = grab("AppleRawCurrentCapacity") or grab("CurrentCapacity")
    temp_raw = grab("Temperature")  # tenths of a degree C, if present

    if design is not None:
        row["design_capacity_mAh"] = design
    if max_cap is not None:
        row["max_capacity_mAh"] = max_cap
    if current is not None:
        row["current_capacity_mAh"] = current
    if temp_raw is not None:
        row["temperature_c"] = round(temp_raw / 100.0, 1)

    # Recompute health_pct from raw mAh if we have both and system_profiler
    # didn't give us a clean percentage.
    if row["health_pct"] is None and design and max_cap:
        row["health_pct"] = round((max_cap / design) * 100, 2)

    return row


def append_row(row):
    file_exists = CSV_PATH.exists()
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    data = get_power_data()
    row = extract_row(data)
    row = enrich_with_ioreg(row)
    append_row(row)
    print(f"Logged: {row}")


if __name__ == "__main__":
    main()
