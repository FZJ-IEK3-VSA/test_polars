"""Compare the CPU features of this machine with those the polars runtimes need.

Nothing here loads a polars binary, so the report also works on a CPU where
`import polars` crashes with "Fatal Python error: Illegal instruction".

polars ships one Python package and up to three compiled runtimes:
- polars-runtime-32 (always installed with polars on conda-forge)
- polars-runtime-64
- polars-runtime-compat (built for older CPUs, polars prefers it when installed)
On x86_64 each runtime records the CPU features it was compiled for in
`BUILD_FEATURE_FLAGS`. polars only warns when one of them is missing.
"""

import importlib.util
import os
import platform
import sys
from pathlib import Path

RUNTIMES = ["32", "64", "compat"]

# name in polars' feature list -> name in /proc/cpuinfo
CPUINFO_NAMES = {
    "sse3": "pni",
    "sse4.1": "sse4_1",
    "sse4.2": "sse4_2",
    "cmpxchg16b": "cx16",
    "lzcnt": "abm",
}

# Features no polars runtime asks for, but which a binary could still use by mistake
EXTRA_CPUINFO_FLAGS = [
    "aes",
    "f16c",
    "avx512f",
    "avx512bw",
    "avx512vl",
    "sha_ni",
    "xsave",
]


def load_polars_cpu_check():
    """Load polars/_cpu_check.py without running polars/__init__.py."""
    spec = importlib.util.find_spec("polars")
    if spec is None:
        return None
    path = Path(spec.submodule_search_locations[0]) / "_cpu_check.py"
    module_spec = importlib.util.spec_from_file_location("polars_cpu_check", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def runtime_build_flags():
    """Return {runtime: [feature, ...]} for every installed runtime."""
    flags = {}
    for runtime in RUNTIMES:
        name = f"_polars_runtime_{runtime}"
        if importlib.util.find_spec(name) is None:
            continue
        # The package __init__ only reads build_feature_flags.py, the binary
        # is in the _polars_runtime submodule, which is not imported here.
        package = importlib.import_module(name)
        flags[runtime] = [
            f.lstrip("+")
            for f in package.BUILD_FEATURE_FLAGS.split(",")
            if f and not f.startswith("-") and f != "ctr-static"
        ]
    return flags


def read_cpuinfo():
    """Return (model name, set of flags) from /proc/cpuinfo, or (None, None)."""
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return None, None
    model, flags = None, set()
    for line in path.read_text().splitlines():
        key, _, value = line.partition(":")
        key = key.strip()
        if key == "model name" and model is None:
            model = value.strip()
        elif key == "flags" and not flags:
            flags = set(value.split())
    return model, flags


def host_microarchitecture():
    try:
        import archspec.cpu
    except ImportError:
        return "archspec not installed"
    host = archspec.cpu.host()
    return f"{host.name} (generic: {host.generic.name})"


def mark(value):
    return {True: "yes", False: "NO", None: "-"}[value]


def main():
    print(
        f"python {sys.version.split()[0]} on {platform.system()} {platform.machine()}"
    )
    print(f"microarchitecture (archspec): {host_microarchitecture()}")
    model, cpuinfo_flags = read_cpuinfo()
    if model:
        print(f"CPU model: {model}")

    cpu_check = load_polars_cpu_check()
    if cpu_check is None:
        print("polars is not installed")
        return 0
    cpuid_flags = cpu_check._read_cpu_flags()
    if not cpuid_flags:
        print("polars runs no CPU feature check on this architecture")

    build_flags = runtime_build_flags()
    print(f"installed polars runtimes: {', '.join(build_flags) or 'none'}")

    features = []
    for runtime_flags in build_flags.values():
        features += [f for f in runtime_flags if f not in features]

    header = ["feature", "CPUID (polars check)"]
    if cpuinfo_flags is not None:
        header.append("/proc/cpuinfo")
    header += [f"needed by {runtime}" for runtime in build_flags]
    rows = []
    for feature in features:
        row = [feature, mark(cpuid_flags.get(feature))]
        if cpuinfo_flags is not None:
            row.append(mark(CPUINFO_NAMES.get(feature, feature) in cpuinfo_flags))
        row += ["x" if feature in flags else "" for flags in build_flags.values()]
        rows.append(row)
    if cpuinfo_flags is not None:
        for flag in EXTRA_CPUINFO_FLAGS:
            row = [flag, "-", mark(flag in cpuinfo_flags)]
            rows.append(row + [""] * len(build_flags))

    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    for row in [header, ["-" * w for w in widths]] + rows:
        print("  ".join(str(cell).ljust(w) for cell, w in zip(row, widths)))

    summary = []
    for runtime, flags in build_flags.items():
        missing = [f for f in flags if not cpuid_flags.get(f)]
        if not cpuid_flags or not flags:
            line = f"runtime {runtime}: no CPU feature check on this architecture"
        elif missing:
            line = f"runtime {runtime}: CPU lacks {', '.join(missing)}, importing it will likely crash"
        else:
            line = (
                f"runtime {runtime}: CPU has all {len(flags)} features it was built for"
            )
        print(line)
        summary.append(f"- {line}")

    if cpuinfo_flags is not None:
        print(f"all /proc/cpuinfo flags: {' '.join(sorted(cpuinfo_flags))}")

    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(
                f"### CPU features ({platform.machine()}, {host_microarchitecture()})\n\n"
            )
            fh.write("\n".join(summary) + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
