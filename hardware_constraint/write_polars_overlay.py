"""Write overlay channels with polars-runtime-32/64 records that declare a minimum x86-64 level.

usage: python write_polars_overlay.py <feedstock recipe dir> <output dir>

<feedstock recipe dir> is the `recipe` directory of a conda-forge-repodata-patches-feedstock clone
in which `python show_diff.py --subdirs linux-64` has downloaded the raw repodata into `cache/`.

Writes two channels for linux-64, to be put in front of conda-forge with strict channel priority
(the overlay then replaces conda-forge's polars-runtime-32/64 completely):

- patch_only: the existing records with `_x86_64-microarch-level >=3` added, like a repodata patch would do.
- variants: every existing record twice, like microarch variants built by the feedstock would be:
  a level-3 build (build number + 100, `_x86_64-microarch-level >=3`) and a baseline build
  (build number unchanged, `_x86_64-microarch-level >=2`, compiled like polars-runtime-compat).
"""

import copy
import json
import os
import sys

import zstandard

recipe_dir, out_dir = sys.argv[1:]
with zstandard.open(
    os.path.join(recipe_dir, "cache", "linux-64", "repodata_from_packages.json.zst")
) as fh:
    raw = json.load(fh)

runtimes = {
    fn: record
    for fn, record in raw["packages.conda"].items()
    if record["name"] in ("polars-runtime-32", "polars-runtime-64")
}
print(f"{len(runtimes)} polars-runtime-32/64 records")


def with_level(record, level, build_offset, suffix):
    record = copy.deepcopy(record)
    record["depends"] = [*record["depends"], f"_x86_64-microarch-level >={level}"]
    record["build_number"] += build_offset
    record["build"] = f"{record['build']}_{suffix}"
    fn = f"{record['name']}-{record['version']}-{record['build']}.conda"
    return fn, record


channels = {
    "patch_only": dict(with_level(r, 3, 0, "x86_64_v3") for r in runtimes.values()),
    "variants": dict(
        [with_level(r, 3, 100, "x86_64_v3") for r in runtimes.values()]
        + [with_level(r, 2, 0, "x86_64_v2") for r in runtimes.values()]
    ),
}
for name, packages in channels.items():
    for subdir, pkgs in (("linux-64", packages), ("noarch", {})):
        os.makedirs(os.path.join(out_dir, name, subdir), exist_ok=True)
        repodata = {
            "info": {"subdir": subdir},
            "packages": {},
            "packages.conda": pkgs,
            "repodata_version": 1,
        }
        with open(os.path.join(out_dir, name, subdir, "repodata.json"), "w") as fh:
            json.dump(repodata, fh)
    print(name, len(packages), "records")
