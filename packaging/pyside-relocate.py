"""Set relocatable RUNPATH on our source-built PySide/Shiboken ELF libraries."""
import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sysconfig
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    patchelf = shutil.which("patchelf")
    if not patchelf:
        raise RuntimeError("The source-built patchelf build dependency is missing")
    site = Path(sysconfig.get_path("platlib", vars={
        "base": str(prefix), "platbase": str(prefix),
    }))
    candidates = []
    for name in ("PySide6", "shiboken6"):
        candidates.extend((site / name).glob("*.so*"))
    for pattern in ("libpyside6*.so*", "libshiboken6*.so*"):
        candidates.extend((prefix / "lib").glob(pattern))
    libraries = sorted({path.resolve() for path in candidates if path.is_file()})
    if not libraries:
        raise ValueError("No installed source-built PySide/Shiboken libraries found")
    for path in libraries:
        if not path.is_relative_to(prefix):
            raise ValueError(f"Library escaped installation prefix: {path}")
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError(f"Expected an ELF library: {path}")
        # A Flatpak cache may use hard links. Replace our output inode before
        # patchelf so another cached artifact cannot change with this one.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(path, temporary)
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        subprocess.run([
            patchelf, "--set-rpath",
            "$ORIGIN:/app/lib:$ORIGIN/../shiboken6", str(path),
        ], check=True)
        print(f"Set source library RUNPATH: {path}")


if __name__ == "__main__":
    main()
