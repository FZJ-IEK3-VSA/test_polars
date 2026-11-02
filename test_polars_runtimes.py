"""Import polars with every installed runtime in a fresh process and report crashes.

An illegal instruction kills the Python process, so every import runs in a
subprocess: once with polars' own runtime selection ("default", which prefers
compat > 64 > 32) and once per installed runtime via POLARS_FORCE_PKG.
On Linux, a crash is repeated under gdb to show the faulting instruction.

Exits with 1 if the default import fails.
"""

import argparse
import importlib.util
import os
import shutil
import signal
import subprocess
import sys

RUNTIMES = ["32", "64", "compat"]

SNIPPET = """
import polars as pl
import polars._plr as plr

df = pl.DataFrame({"key": [1, 2, 3, 1], "value": [1.0, 2.5, 3.5, 4.0]})
out = df.group_by("key").agg(pl.col("value").sum()).sort("key")
assert out["value"].to_list() == [5.0, 2.5, 3.5], out
print(f"polars {pl.__version__} loaded {plr.RUNTIME_REPR}")
"""

WINDOWS_ILLEGAL_INSTRUCTION = 0xC000001D


def installed_runtimes():
    return [rt for rt in RUNTIMES if importlib.util.find_spec(f"_polars_runtime_{rt}")]


def polars_env(runtime):
    env = dict(os.environ)
    env.pop("POLARS_PREFER_PKG", None)
    env.pop("POLARS_FORCE_PKG", None)
    if runtime != "default":
        env["POLARS_FORCE_PKG"] = runtime
    return env


def describe(returncode):
    if returncode == 0:
        return "ok"
    if returncode < 0:
        try:
            return f"crashed ({signal.Signals(-returncode).name})"
        except ValueError:
            return f"crashed (signal {-returncode})"
    if returncode == WINDOWS_ILLEGAL_INSTRUCTION:
        return "crashed (STATUS_ILLEGAL_INSTRUCTION)"
    return f"failed (exit code {returncode})"


def run_import(runtime, timeout):
    cmd = [sys.executable, "-X", "faulthandler", "-W", "always", "-c", SNIPPET]
    try:
        proc = subprocess.run(
            cmd,
            env=polars_env(runtime),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout:.0f} s", "", ""
    return describe(proc.returncode), proc.stdout, proc.stderr


def faulting_instruction(runtime, timeout):
    """Run the import under gdb and return what it says about the crash site."""
    gdb = shutil.which("gdb")
    if gdb is None:
        return "gdb not installed"
    cmd = [
        gdb, "-q", "-batch",
        "-ex", "set pagination off",
        "-ex", "run",
        "-ex", "x/i $pc",
        "-ex", "info symbol $pc",
        "-ex", "bt 8",
        "--args", sys.executable, "-c", SNIPPET,
    ]  # fmt: skip
    try:
        proc = subprocess.run(
            cmd,
            env=polars_env(runtime),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"gdb timed out after {timeout:.0f} s"
    lines = proc.stdout.splitlines()
    start = next((i for i, line in enumerate(lines) if "received signal" in line), None)
    if start is None:
        return "gdb did not catch a signal:\n" + "\n".join(lines[-10:])
    return "\n".join(lines[start:])


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeout", type=float, default=900, help="seconds per import")
    args = parser.parse_args()

    runtimes = installed_runtimes()
    print(f"installed polars runtimes: {', '.join(runtimes)}")

    results = []
    for runtime in ["default"] + runtimes:
        outcome, stdout, stderr = run_import(runtime, args.timeout)
        loaded = stdout.strip().splitlines()[-1] if outcome == "ok" else ""
        results.append((runtime, outcome, loaded))

        print(f"::group::runtime {runtime}: {outcome}")
        print(stdout + stderr)
        print("::endgroup::")
        if "SIG" in outcome and sys.platform.startswith("linux"):
            print(f"gdb, runtime {runtime}:")
            print(faulting_instruction(runtime, args.timeout))

    header = ["runtime", "result", "output"]
    widths = [max(len(r[i]) for r in [header] + results) for i in range(len(header))]
    print()
    for row in [header, ["-" * w for w in widths]] + results:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))

    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("| " + " | ".join(header) + " |\n")
            fh.write("|" + "---|" * len(header) + "\n")
            for row in results:
                fh.write("| " + " | ".join(row) + " |\n")
            fh.write("\n")

    if results[0][1] != "ok":
        print("`import polars` fails on this CPU")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
