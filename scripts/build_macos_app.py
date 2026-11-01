"""Build a local Apple Silicon .app bundle with PyInstaller."""

from __future__ import annotations

import platform
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = Path(os.environ.get("FICHAS_MEDICAS_BUILD_DIR", ROOT)).expanduser().resolve()


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("El empaquetado .app debe ejecutarse en macOS.")
    if platform.machine() != "arm64":
        raise SystemExit("Esta configuración crea una app arm64; ejecútala con Python nativo Apple Silicon.")

    templates = ROOT / "fichas_medicas" / "templates"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "FichasMedicas",
        "--osx-bundle-identifier",
        "mx.fichasmedicas.desktop",
        "--target-arch",
        "arm64",
        "--collect-all",
        "customtkinter",
        "--add-data",
        f"{templates}:fichas_medicas/templates",
        "--distpath",
        str(BUILD_ROOT / "dist"),
        "--workpath",
        str(BUILD_ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(BUILD_ROOT / "build" / "pyinstaller-spec"),
        str(ROOT / "fichas_medicas" / "main.py"),
    ]
    build_env = {**os.environ, "PYINSTALLER_CONFIG_DIR": str(BUILD_ROOT / "build" / "pyinstaller-config")}
    subprocess.run(command, cwd=ROOT, env=build_env, check=True, shell=False)
    app_bundle = BUILD_ROOT / "dist" / "FichasMedicas.app"
    try:
        subprocess.run(["xattr", "-cr", str(app_bundle)], check=True, shell=False)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", str(app_bundle)],
                       check=True, shell=False)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app_bundle)], check=True, shell=False)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_macos_bundle.py"), str(app_bundle)],
                       cwd=ROOT, env=build_env, check=True, shell=False)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "No se pudo firmar el bundle. Si el checkout agrega metadatos Finder/File Provider, "
            "reintenta con FICHAS_MEDICAS_BUILD_DIR=/private/tmp/fichas-medicas-build."
        ) from exc
    print(f"App creada y verificada en: {app_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
