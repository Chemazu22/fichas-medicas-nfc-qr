"""Release checks for the local Apple Silicon application bundle."""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_BUNDLE_ID = "mx.fichasmedicas.desktop"
APP_EXECUTABLE = "FichasMedicas"
UUID_HTML = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.html$")
UUID_PNG = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.png$")
PRIVATE_NAMES = {"fichas_medicas.sqlite3", "config.json", "publication_state.json"}
PRIVATE_SUFFIXES = (".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db")


class BundleValidationError(RuntimeError):
    pass


def validate_bundle(app: Path) -> list[str]:
    """Check bundle structure, arm64 architecture, signature and private-data exclusion."""
    if sys.platform != "darwin":
        raise BundleValidationError("La validación del bundle requiere macOS.")
    app = app.expanduser().resolve()
    if not app.is_dir() or app.suffix != ".app":
        raise BundleValidationError(f"No se encontró una aplicación .app: {app}")

    info_path = app / "Contents" / "Info.plist"
    executable = app / "Contents" / "MacOS" / APP_EXECUTABLE
    profile_template = app / "Contents" / "Resources" / "fichas_medicas" / "templates" / "medical_profile.html"
    stylesheet = app / "Contents" / "Resources" / "fichas_medicas" / "templates" / "styles.css"
    for required in (info_path, executable, profile_template, stylesheet):
        if not required.is_file():
            raise BundleValidationError(f"Falta un recurso requerido: {required.relative_to(app)}")

    try:
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise BundleValidationError(f"Info.plist no es válido: {exc}") from exc
    if info.get("CFBundleIdentifier") != EXPECTED_BUNDLE_ID:
        raise BundleValidationError("El identificador del bundle no coincide con el esperado.")

    architectures = _run(["lipo", "-archs", str(executable)]).stdout.split()
    if "arm64" not in architectures:
        raise BundleValidationError(f"El ejecutable no incluye arm64: {architectures}")
    _run(["codesign", "--verify", "--deep", "--strict", str(app)])

    toolkit_metadata = list((app / "Contents" / "Resources").glob("customtkinter-*.dist-info/METADATA"))
    if len(toolkit_metadata) != 1:
        raise BundleValidationError("No se encontró un único METADATA de CustomTkinter en el bundle.")
    version = _metadata_version(toolkit_metadata[0])
    try:
        version_pair = tuple(int(part) for part in version.split(".")[:2]) if version else ()
    except ValueError:
        version_pair = ()
    if len(version_pair) != 2 or not (5, 2) <= version_pair < (6, 0):
        raise BundleValidationError(f"La versión de CustomTkinter no es la declarada por el proyecto: {version}")

    violations = _find_private_artifacts(app)
    if violations:
        raise BundleValidationError("El bundle contiene archivos privados o generados: " + ", ".join(violations[:10]))

    return [
        f"Bundle ID: {EXPECTED_BUNDLE_ID}",
        f"Arquitectura: {', '.join(architectures)}",
        f"CustomTkinter: {version}",
        "Firma ad hoc: verificada",
        "Datos SQLite/configuración/QR/perfiles generados: ausentes",
    ]


def _find_private_artifacts(app: Path) -> list[str]:
    violations = []
    for path in app.rglob("*"):
        if path.name in PRIVATE_NAMES or path.name.endswith(PRIVATE_SUFFIXES):
            violations.append(str(path.relative_to(app)))
        elif UUID_HTML.fullmatch(path.name) or UUID_PNG.fullmatch(path.name):
            violations.append(str(path.relative_to(app)))
    return violations


def _metadata_version(metadata: Path) -> str | None:
    for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Version:"):
            return line.partition(":")[2].strip()
    return None


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60, shell=False)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise BundleValidationError(f"Falló la verificación {args[0]}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "dist" / "FichasMedicas.app")
    args = parser.parse_args()
    try:
        for item in validate_bundle(args.app):
            print(item)
    except BundleValidationError as exc:
        parser.exit(1, f"Validación fallida: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
