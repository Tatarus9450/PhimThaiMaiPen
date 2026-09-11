#!/usr/bin/env python3
"""Install the two upstream PyO3 source trees after an offline Cargo build.

Use the module name and Python-source layout from upstream pyproject.toml.
The sdist's PKG-INFO supplies its original dependency/extra metadata. Nothing
here consumes a downloaded binary wheel or invokes a Python build backend.
"""

import argparse
import csv
import json
import shutil
import sysconfig
import tomllib
from email.parser import Parser
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, default=Path("/app"))
    args = parser.parse_args()
    root = Path.cwd()
    config = tomllib.loads((root / "pyproject.toml").read_text())
    project = config["project"]
    maturin = config["tool"]["maturin"]
    cargo_path = root / maturin["manifest-path"]
    cargo = tomllib.loads(cargo_path.read_text())
    metadata_text = (root / "PKG-INFO").read_text()
    metadata = Parser().parsestr(metadata_text)
    name, version = project["name"], cargo["package"]["version"]
    if (metadata["Name"], metadata["Version"]) != (name, version):
        raise ValueError("sdist metadata and source version disagree")
    module_package, module_name = maturin["module-name"].rsplit(".", 1)
    if module_package != name:
        raise ValueError("Unexpected upstream Python module layout")
    site = Path(sysconfig.get_path("platlib", vars={
        "base": str(args.prefix), "platbase": str(args.prefix),
    }))
    site.mkdir(parents=True, exist_ok=True)
    package = site / name
    shutil.copytree(root / maturin["python-source"] / name, package)
    library = cargo_path.parent / "target/release" / f"lib{cargo['lib']['name']}.so"
    if library.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("Cargo did not produce an ELF extension")
    # Build uses this runtime's interpreter. CPython's concrete suffix remains
    # valid even though both upstream crates also opt into the abi3 API.
    shutil.copy2(library, package / f"{module_name}{sysconfig.get_config_var('EXT_SUFFIX')}")
    info = site / f"{name}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(metadata_text)
    (info / "INSTALLER").write_text("flatpak-source-cargo\n")
    license_dir = info / "licenses"
    license_dir.mkdir()
    core_license = root / name / "LICENSE"
    if not core_license.is_file():
        core_license = root / "LICENSE"
    shutil.copy2(core_license, license_dir / "LICENSE")

    # Rust links crates into the extension. Keep their source-supplied notices,
    # plus the complete upstream lock and machine-readable license inventory.
    notices = args.prefix / "share/licenses" / f"python-{name}-crates"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cargo_path.parent / "Cargo.lock", notices / "Cargo.lock")
    inventory = []
    for crate in sorted((root / "cargo/vendor").iterdir()):
        crate_metadata = tomllib.loads((crate / "Cargo.toml").read_text())["package"]
        license_files = []
        explicit = crate_metadata.get("license-file")
        for source in sorted(crate.rglob("*")):
            relative = source.relative_to(crate)
            conventional = source.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE"))
            if source.is_file() and (conventional or str(relative) == explicit):
                target = notices / crate.name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                license_files.append(str(relative))
        inventory.append({"name": crate_metadata["name"], "version": crate_metadata["version"],
                          "license": crate_metadata.get("license"), "license_file": explicit,
                          "notice_files": license_files})
    (notices / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    # Flatpak strips ELF files later; empty hashes/sizes remain valid RECORDs.
    files = [*package.rglob("*"), *info.rglob("*"), *notices.rglob("*")]
    with (info / "RECORD").open("w", newline="") as stream:
        writer = csv.writer(stream)
        import os
        for path in sorted(p for p in files if p.is_file()):
            writer.writerow([os.path.relpath(path, site), "", ""])
        writer.writerow([f"{info.name}/RECORD", "", ""])
    print(json.dumps({"installed": name, "version": version, "vendored_crates": len(inventory)}))


if __name__ == "__main__":
    main()
