# test_polars

Investigates `Fatal Python error: Illegal instruction` while importing polars on the self-hosted runners, which broke the
CI of [RESKit PR #375](https://github.com/FZJ-IEK3-VSA/RESKit/pull/375) at the start of November 2026
(statsmodels → polars 2.1.0).

The pyarrow/numpy problem from the same PR is investigated in
[julian-belina/test_polars_and_pyarrow](https://github.com/julian-belina/test_polars_and_pyarrow).

## What is known so far

- On conda-forge, `polars` always depends on `polars-runtime-32`. On x86_64 that runtime is compiled for
  `sse3, ssse3, sse4.1, sse4.2, popcnt, cmpxchg16b, avx, avx2, fma, bmi1, bmi2, lzcnt, pclmulqdq, movbe`
  (about x86-64-v3, see the feedstock's
  [build script](https://github.com/conda-forge/polars-feedstock/blob/main/recipe/build_polars_runtime.sh)).
  These flags are the same for 2.0.0 and 2.1.0.
- `polars-runtime-compat` only needs `sse3, ssse3, sse4.1, sse4.2, popcnt, cmpxchg16b`. When it is installed,
  polars loads it first.
- In the last green self-hosted run (2026-10-09) the environment contained `wombat 0.13.4`, which depends on
  `polars-lts-cpu`, which depends on `polars-runtime-compat`. So polars ran on the compat runtime.
- `wombat 0.13.5` (published 2026-10-29) dropped `polars-lts-cpu`. Since then only `polars-runtime-32` is installed,
  and the crash happens while loading its binary (`_plr.py`, line 39 in `rt_32`).
- The runners are Proxmox VMs. Proxmox's default CPU types (`x86-64-v2-AES`, `kvm64`) have no AVX/AVX2.
  polars only *warns* about missing CPU features, and pytest holds warnings back until the end of the run,
  which never came.

## Test suite

Every job creates a fresh conda-forge environment with `mamba create`, prints it with `mamba list` and runs plain
Python scripts. The workflow runs on push, or manually with a JSON list of runners.

| File | What it does |
|---|---|
| [`.github/workflows/test_polars_cpu.yml`](.github/workflows/test_polars_cpu.yml) | Job `MicroarchLevel`: prints conda's virtual packages and asks the solver which `_x86_64-microarch-level` (1 to 4) it can install on the runner. Job `TestPolarsRuntimes`: polars version × extra package (none, `polars-runtime-compat`, `wombat=0.13.4`, `wombat=0.13.5`) × runner. On GitHub-hosted Linux it also runs the imports under qemu with older CPU models. |
| [`polars_cpu_report.py`](polars_cpu_report.py) | Lists the CPU features of the machine (CPUID as polars reads it, `/proc/cpuinfo`, archspec) next to the features every installed polars runtime was built for. Never loads a polars binary, so it also works where `import polars` crashes. |
| [`test_polars_runtimes.py`](test_polars_runtimes.py) | Imports polars in a subprocess with the default runtime selection and with each installed runtime (`POLARS_FORCE_PKG`). Reports crashes (SIGILL, `STATUS_ILLEGAL_INSTRUCTION`) and, on Linux with gdb installed, the faulting instruction. `--qemu-cpu MODEL` runs the imports under `qemu-x86_64 -cpu MODEL`. Fails only if the default import fails. |

The workflow has no `pull_request` trigger on purpose: the repository is public and uses the organization's
self-hosted runners, so forks must not be able to start jobs on them.
