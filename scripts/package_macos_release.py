"""Create and verify a local ZIP handoff for the macOS application bundle."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__:
    from .validate_macos_bundle import BundleValidationError, validate_bundle
else:
    from validate_macos_bundle import BundleValidationError, validate_bundle


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP = ROOT / "dist" / "FichasMedicas.app"
DEFAULT_OUTPUT = ROOT / "dist"


def package_release(app: Path, output_dir: Path) -> tuple[Path, Path, str]:
    if sys.platform != "darwin":
        raise RuntimeError("El empaquetado ZIP debe ejecutarse en macOS.")
    app = app.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    validate_bundle(app)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "FichasMedicas-macOS-arm64.zip"
    checksum_file = output_dir / f"{archive.name}.sha256"

    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)],
        check=True,
        shell=False,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="fichas-release-") as temporary_dir:
            subprocess.run(
                ["ditto", "-x", "-k", str(archive), temporary_dir],
                check=True,
                shell=False,
            )
            extracted_app = Path(temporary_dir) / app.name
            validate_bundle(extracted_app)
        digest = _sha256(archive)
        checksum_file.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    except Exception:
        archive.unlink(missing_ok=True)
        checksum_file.unlink(missing_ok=True)
        raise
    return archive, checksum_file, digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", nargs="?", type=Path, default=DEFAULT_APP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        archive, checksum, digest = package_release(args.app, args.output_dir)
    except (BundleValidationError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"No se pudo crear la entrega: {exc}\n")
    print(f"ZIP: {archive}")
    print(f"SHA-256: {digest}")
    print(f"Checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
