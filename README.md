# Battery Tracker — Setup

## 1. Install matplotlib (for the notebook only)
```
python3 -m pip install matplotlib
```
`log_battery.py` has no dependencies beyond the standard library.

## 2. Run the logger manually first — DO NOT skip this
```
python3 /Users/anmolmathur/Documents/Code/mac_battery/files/log_battery.py
```
Check the printed row. If `health_pct`, `cycle_count`, or `charge_pct` are `None`,
the `system_profiler`/`ioreg` key names have shifted on your macOS version and the
parsing in `extract_row()` / `enrich_with_ioreg()` needs adjusting before you automate.

To inspect raw data yourself:
```
system_profiler SPPowerDataType -json | less
ioreg -rn AppleSmartBattery | less
```

## 3. Scheduling (launchd)
Scheduling is done with a launchd LaunchAgent, not cron:
`~/Library/LaunchAgents/com.anmolmathur.battery-tracker.plist`
(runs every 3 hours via `StartInterval`).

Reload after editing the plist or the script:
```
launchctl bootout   gui/$(id -u)/com.anmolmathur.battery-tracker
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.anmolmathur.battery-tracker.plist
launchctl kickstart -k gui/$(id -u)/com.anmolmathur.battery-tracker   # force an immediate run
```
Check it worked: `last exit code` should be `0`, not `78`.
```
launchctl print gui/$(id -u)/com.anmolmathur.battery-tracker | grep -E "state|last exit code|runs"
```

### ⚠️ macOS TCC gotcha — DATA MUST NOT LIVE UNDER ~/Documents
macOS TCC (Privacy & Security) blocks *background* LaunchAgents from reading or
writing `~/Documents`, `~/Desktop`, `~/Downloads`, and the home root itself —
even for files you own with wide-open permissions. A daemon touching them gets
`Operation not permitted`, and launchd fails to spawn the job with
`last exit code = 78` (EX_CONFIG) because it cannot open its log file. This
typically bites *after a reboot*, when the agent reloads in a clean daemon
context with no inherited file-access rights.

Therefore the log and CSV live under **`~/Library/Application Support/mac_battery/`**,
which is TCC-free for daemons. The script itself may stay under `~/Documents`
(launchd only needs to *execute* it; execution is not TCC-gated).

If you ever must keep data under `~/Documents`, the alternative is granting the
Python interpreter **Full Disk Access** in
System Settings → Privacy & Security → Full Disk Access (manual, and fragile
if the interpreter path changes).

## 4. Analyze whenever you want
Open `analyze_battery.ipynb` in VSCode and run all cells.
CSV lives at: `~/Library/Application Support/mac_battery/battery_log.csv`

The notebook has three cells:

**Cell 1 — Load data**
Reads the CSV, parses timestamps, casts `cycle_count` and `charge_pct` to int and
`health_pct` to float, and sorts rows by timestamp.

**Cell 2 — Health & cycle count over time**
Dual time-series: battery health (%) on the left axis and charge cycle count on the
right axis, both plotted against date.

**Cell 3 — Health vs charge count + health vs date**
- *Battery Health vs Charge Count*: health (%) on Y, cycle count on X; Y-axis
  zoomed to 70–100% so degradation is visible.
- *Battery Health vs Date*: health (%) on Y, date on X; one point per day using
  the **mode** of that day's readings; Y-axis also 70–100%.
