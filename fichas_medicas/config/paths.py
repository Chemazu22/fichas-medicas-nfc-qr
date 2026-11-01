"""Rutas persistentes de la aplicación."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRECTORY_NAME = "FichasMedicas"


def data_directory() -> Path:
    """Devuelve la carpeta persistente, permitiendo un override para pruebas."""
    override = os.environ.get("FICHAS_MEDICAS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRECTORY_NAME
    if os.name == "nt":  # Permite ejecutar utilidades de desarrollo en Windows.
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / APP_DIRECTORY_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_DIRECTORY_NAME


def database_path() -> Path:
    return data_directory() / "fichas_medicas.sqlite3"


def profiles_directory() -> Path:
    """Directorio configurable de perfiles públicos generados."""
    override = os.environ.get("FICHAS_MEDICAS_PROFILES_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return data_directory() / "profiles"


def qr_directory() -> Path:
    """Directorio privado para PNG de códigos QR."""
    override = os.environ.get("FICHAS_MEDICAS_QR_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return data_directory() / "qr"


def ensure_data_directory() -> Path:
    """Crea la carpeta de datos con permisos privados cuando el sistema lo permite."""
    path = data_directory()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path
