# test_polars

Investigates `Fatal Python error: Illegal instruction` while importing polars on the self-hosted runners, which broke the
CI of [RESKit PR #375](https://github.com/FZJ-IEK3-VSA/RESKit/pull/375) at the start of November 2026
(statsmodels → polars 2.1.0).

The pyarrow/numpy problem from the same PR is investigated in
[julian-belina/test_polars_and_pyarrow](https://github.com/julian-belina/test_polars_and_pyarrow).

## Result

The self-hosted runners' CPU has no AVX/AVX2, and polars' default runtime needs them.

- All self-hosted runners that ran jobs (`PROXMOXGithubRunner1`, `3`, `4`, `5`) have the CPU model
  `QEMU Virtual CPU version 2.5+`. archspec and conda see it as `nehalem` (`__archspec=1=nehalem`, x86-64-v2).
  It has SSE4.2, POPCNT and CX16, but no AVX, AVX2, FMA, BMI1/2, LZCNT, PCLMULQDQ or MOVBE.
- On conda-forge, `polars` always depends on `polars-runtime-32`. On x86_64 that runtime is compiled for
  `sse3, ssse3, sse4.1, sse4.2, popcnt, cmpxchg16b, avx, avx2, fma, bmi1, bmi2, lzcnt, pclmulqdq, movbe`
  (see the feedstock's [build script](https://github.com/conda-forge/polars-feedstock/blob/main/recipe/build_polars_runtime.sh)).
  These flags are the same for 2.0.0 and 2.1.0.
- Loading `polars-runtime-32` on the runners crashes with SIGILL at `vmovdqa`, an AVX instruction, while the dynamic
  loader runs the library's initializers. This happens for polars 1.44.2, 2.0.0 and 2.1.0.
- polars 2.x prints a `RuntimeWarning: Missing required CPU features` right before the crash, but pytest only shows
  warnings at the end of a run, which never comes. polars 1.44.2 crashes without a warning: its conda-forge build does
  not record the features it was built for
  ([polars-feedstock#369](https://github.com/conda-forge/polars-feedstock/issues/369)).
- `polars-runtime-compat` only needs `sse3, ssse3, sse4.1, sse4.2, popcnt, cmpxchg16b`. When it is installed,
  polars loads it first, and it works on the runners.

| self-hosted job | polars-runtime-compat installed | result |
|---|---|---|
| polars 1.44.2, 2.0.0, 2.1.0 alone | no | crash |
| … with `wombat=0.13.5` | no | crash |
| … with `polars-runtime-compat` | yes | ok |
| … with `wombat=0.13.4` (→ `polars-lts-cpu` → `polars-runtime-compat`) | yes | ok |

So the crash did not come with polars 2.1.0. It came with `wombat 0.13.5` (published 2026-10-29), which dropped
`polars-lts-cpu`, so `polars-runtime-compat` is no longer installed. RESKit gets polars through statsmodels and wombat.
In the last green RESKit run (2026-10-09) the environment had `wombat 0.13.4` and polars ran on the compat runtime.

On the GitHub-hosted `ubuntu-latest` (zen2, x86-64-v3) all combinations work.

### Fixes for RESKit

Either of:

- add `polars-runtime-compat` to RESKit's `requirements.yml`. It works on any x86_64 CPU with SSE4.2, and polars
  prefers it when installed.
- set the CPU type of the Proxmox VMs to `host` (or at least `x86-64-v3`). This also helps every other package that is
  built for newer CPUs, and makes numerical code faster.

## Can conda-forge add a hardware constraint?

conda can express "this package needs an x86-64-v3 CPU": the solver sees the CPU as the virtual package `__archspec`,
and conda-forge packages declare a minimum level by depending on
[`_x86_64-microarch-level >=N`](https://conda-forge.org/docs/maintainer/knowledge_base/#microarch). The job
`MicroarchLevel` checks this on the runners:

| spec | self-hosted (`nehalem`) | ubuntu-latest (`zen2`) |
|---|---|---|
| `_x86_64-microarch-level>=2` | installable | installable |
| `_x86_64-microarch-level>=3` | refused | installable |

But it cannot be added to the existing packages with a repodata patch. `polars` depends on `polars-runtime-32`
unconditionally, and conda cannot express "needs x86-64-v3 unless polars-runtime-compat is installed". If a patch
added `_x86_64-microarch-level >=3` to `polars-runtime-32`, the solver could no longer install any polars 2.x on these
runners, not even together with `polars-runtime-compat`.

The fix belongs in the [polars-feedstock](https://github.com/conda-forge/polars-feedstock): build `polars-runtime-32`
(and `-64`) on x86_64 in two microarchitecture variants, as described in the
[conda-forge docs](https://conda-forge.org/docs/maintainer/knowledge_base/#microarch):

- a level-3 build with today's flags, a higher build number and `_x86_64-microarch-level >=3`,
- a baseline build with the compat flags.

The solver then picks the level-3 build where the CPU supports it and the baseline build elsewhere, and plain
`polars` works on older CPUs without `polars-runtime-compat`.

Dry-run solves on linux-64 (`python=3.12` plus the specs) against conda-forge, with a local channel in front
that replaces `polars-runtime-32`/`-64` with modified copies of the real records. The CPU is faked with
`CONDA_OVERRIDE_ARCHSPEC`. Scripts and full output: [`hardware_constraint/`](hardware_constraint/).

| specs | CPU | conda-forge today | repodata patch | feedstock variants |
|---|---|---|---|---|
| `polars` | nehalem | 2.1.0, runtime-32 (crashes) | polars 1.33.1, from before the runtime split | 2.1.0, baseline runtime-32 |
| `polars=2.1.0` | nehalem | runtime-32 (crashes) | unsolvable | baseline runtime-32 |
| `polars=2.1.0 polars-runtime-compat` | nehalem | runtime-32 + compat | unsolvable | baseline runtime-32 + compat |
| `polars` | skylake | 2.1.0, runtime-32 | 2.1.0, runtime-32 | 2.1.0, level-3 runtime-32 |

## Test suite

Every job creates a fresh conda-forge environment with `mamba create`, prints it with `mamba list` and runs plain
Python scripts. The workflow runs on push, or manually with a JSON list of runners.

| File | What it does |
|---|---|
| [`.github/workflows/test_polars_cpu.yml`](.github/workflows/test_polars_cpu.yml) | Job `MicroarchLevel`: prints conda's virtual packages and asks the solver which `_x86_64-microarch-level>=N` it can install on the runner. Job `TestPolarsRuntimes`: polars version × extra package (none, `polars-runtime-compat`, `wombat=0.13.4`, `wombat=0.13.5`) × runner. |
| [`polars_cpu_report.py`](polars_cpu_report.py) | Lists the CPU features of the machine (CPUID as polars reads it, `/proc/cpuinfo`, archspec) next to the features every installed polars runtime was built for. Never loads a polars binary, so it also works where `import polars` crashes. |
| [`test_polars_runtimes.py`](test_polars_runtimes.py) | Imports polars in a subprocess with the default runtime selection and with each installed runtime (`POLARS_FORCE_PKG`). Reports crashes (SIGILL, `STATUS_ILLEGAL_INSTRUCTION`) and, on Linux with gdb installed, the faulting instruction. Fails only if the default import fails. |
| [`hardware_constraint/`](hardware_constraint/) | Local dry-run solves for a repodata patch and for feedstock variants, see above. |

The workflow has no `pull_request` trigger on purpose: the repository is public and uses the organization's
self-hosted runners, so forks must not be able to start jobs on them.
