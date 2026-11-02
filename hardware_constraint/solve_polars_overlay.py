"""Dry-run solve polars on linux-64 for faked CPUs, with and without the overlay channels.

usage: python solve_polars_overlay.py <overlay dir>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

overlay_dir = Path(sys.argv[1]).resolve()
channels = {
    "conda-forge today": None,
    "repodata patch": "patch_only",
    "feedstock variants": "variants",
}
cpus = ["nehalem", "skylake"]
spec_sets = [
    "polars",
    "polars=2.1.0",
    "polars polars-runtime-compat",
    "polars=2.1.0 polars-runtime-compat",
]

for channel_name, overlay in channels.items():
    for cpu in cpus:
        for specs in spec_sets:
            channel_args = ["-c", "conda-forge"]
            if overlay:
                channel_args = ["-c", (overlay_dir / overlay).as_uri(), *channel_args]
            env = {
                **os.environ,
                "CONDA_OVERRIDE_ARCHSPEC": cpu,
                "CONDA_OVERRIDE_GLIBC": "2.39",
            }
            cmd = [
                "conda",
                "create",
                "--dry-run",
                "--json",
                "--name",
                "overlay_dryrun",
                "--platform",
                "linux-64",
                "--override-channels",
                "--strict-channel-priority",
                *channel_args,
                "python=3.12",
                *specs.split(),
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                shell=os.name == "nt",
            )
            try:
                out = json.loads(proc.stdout)
            except json.JSONDecodeError:
                out = {"error": proc.stdout[-300:] + proc.stderr[-300:]}
            if out.get("success"):
                links = out["actions"]["LINK"]
                picked = sorted(
                    f"{p['name']}={p['version']}={p['build_string']}"
                    for p in links
                    if p["name"].startswith("polars")
                )
                result = " ".join(picked)
            else:
                result = (
                    "UNSOLVABLE: " + " ".join(str(out.get("error", out)).split())[:400]
                )
            print(f"{channel_name} | {cpu} | {specs} | {result}", flush=True)
