"""E8 — the machine every live measurement ran on, read from /proc and os-release.

    python evaluation/hardware.py      (writes evaluation/ENVIRONMENT.json)
"""

import json
import os
import pathlib
import platform

cpu = next(line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name"))
mem_kb = int(next(line.split()[1] for line in open("/proc/meminfo") if line.startswith("MemTotal")))
release = dict(line.rstrip().split("=", 1) for line in open("/etc/os-release") if "=" in line)
info = {
    "cpu": cpu,
    "threads": os.cpu_count(),
    "ram_gib": round(mem_kb / 1024 ** 2),
    "os": f"{release.get('NAME', '').strip(chr(34))}, Linux {platform.release().split('-')[0]}",
}
out = pathlib.Path(__file__).resolve().parent / "ENVIRONMENT.json"
out.write_text(json.dumps(info, indent=2) + "\n")
print(info)
