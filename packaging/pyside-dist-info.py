"""Add source-derived distribution metadata after PySide's CMake install.

CMake installs the bindings without Python dist-info. Read upstream project
metadata and CMake-generated versions; no wheel is downloaded or inspected.
"""
import argparse
import ast
import csv
import os
from pathlib import Path
import shutil
import sysconfig
import tomllib


def configured_version(path):
    for statement in ast.parse(path.read_text()).body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "version"
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            if isinstance(value, str) and value:
                return value
    raise ValueError(f"No generated version found in {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    project = tomllib.loads(
        (args.source_root / "wheel_artifacts/pyproject.toml.base").read_text()
    )["project"]
    site = Path(sysconfig.get_path("platlib", vars={
        "base": str(args.prefix), "platbase": str(args.prefix),
    }))
    versions = {
        "PySide6": configured_version(
            args.build_root / "sources/pyside6/PySide6/_config.py"),
        "shiboken6": configured_version(
            args.build_root / "sources/shiboken6/shibokenmodule/_config.py"),
    }
    if versions["PySide6"] != versions["shiboken6"]:
        raise ValueError("PySide6 and Shiboken source versions differ")

    for name, version in versions.items():
        package = site / name
        if not (package / "__init__.py").is_file():
            raise ValueError(f"CMake package is not installed: {package}")
        info = site / f"{name.lower()}-{version}.dist-info"
        info.mkdir(exist_ok=True)
        license_dir = info / "licenses"
        license_dir.mkdir(exist_ok=True)
        # Retain upstream SPDX license texts and the component's legacy notices.
        for path in sorted((args.source_root / "LICENSES").glob("*.txt")):
            shutil.copyfile(path, license_dir / path.name)
        component = "pyside6" if name == "PySide6" else "shiboken6"
        for path in sorted((args.source_root / "sources" / component).glob("COPYING*")):
            shutil.copyfile(path, license_dir / path.name)
        headers = [
            "Metadata-Version: 2.4",
            f"Name: {name}",
            f"Version: {version}",
            f"Requires-Python: {project['requires-python']}",
            f"License-Expression: {project['license']['text']}",
        ]
        for author in project.get("authors", []):
            headers.append(f"Author-email: {author['name']} <{author['email']}>")
        for label, url in project.get("urls", {}).items():
            headers.append(f"Project-URL: {label}, {url}")
        if name == "PySide6":
            # Same dependencies as Config.init_config's source PySide build.
            headers.extend([
                f"Requires-Dist: shiboken6=={version}",
                'Requires-Dist: tomli>=2.0.1; python_version < "3.11"',
            ])
        for path in sorted(license_dir.iterdir()):
            headers.append(f"License-File: licenses/{path.name}")
        (info / "METADATA").write_text("\n".join(headers) + "\n\n")
        (info / "INSTALLER").write_text("flatpak-builder\n")
        (info / "top_level.txt").write_text(f"{name}\n")
        (info / "SOURCE-BUILD.txt").write_text(
            "Built from Qt for Python source with CMake against the Flatpak Qt runtime.\n"
            "Only the selected modules are installed; no separate wheel Addons/Essentials distributions.\n"
        )
        owned = [path for path in package.rglob("*") if path.is_file()]
        library_pattern = "libpyside6*" if name == "PySide6" else "libshiboken6*"
        owned.extend(path for path in (args.prefix / "lib").glob(library_pattern) if path.is_file())
        owned.extend(path for path in info.rglob("*") if path.is_file() and path.name != "RECORD")
        record = info / "RECORD"
        with record.open("w", newline="") as stream:
            writer = csv.writer(stream)
            # Flatpak strips ELF files after post-install; empty hashes/sizes are
            # permitted by RECORD and avoid recording hashes that stripping changes.
            for path in sorted(set(owned)):
                writer.writerow([os.path.relpath(path, site), "", ""])
            writer.writerow([os.path.relpath(record, site), "", ""])
        print(f"Installed source metadata: {name} {version}")


if __name__ == "__main__":
    main()
