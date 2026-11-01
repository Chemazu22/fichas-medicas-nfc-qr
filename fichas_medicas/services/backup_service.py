"""Respaldos SQLite consistentes y restauración con copia de seguridad previa."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fichas_medicas.config.paths import data_directory
from fichas_medicas.database.connection import Database
from fichas_medicas.database.migrations import CURRENT_SCHEMA_VERSION, migrate

_BACKUP_NAME = re.compile(r"^(?:backup|before-restore)-\d{8}T\d{6}Z-[0-9a-f]{8}\.sqlite3$")


class BackupError(RuntimeError):
    """Error al crear, validar o restaurar un respaldo."""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    size_bytes: int
    modified_at: str
    integrity: str


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_from: Path
    database_path: Path
    safety_backup: Path | None


class BackupService:
    """Trabaja solo con SQLite y guarda respaldos fuera del checkout de la app."""

    def __init__(self, database: Database, backup_dir: Path | str | None = None) -> None:
        self.database = database
        self.backup_dir = Path(backup_dir).expanduser().resolve() if backup_dir else data_directory() / "backups"

    def create_backup(self) -> Path:
        if not self.database.path.is_file():
            raise BackupError("No existe una base de datos para respaldar.")
        self.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._private(self.backup_dir)
        target = self.backup_dir / self._new_name("backup")
        try:
            with self.database.connect() as source, sqlite3.connect(target) as destination:
                source.backup(destination)
                destination.execute("PRAGMA integrity_check")
            self._private(target, file=True)
            if self.integrity_check(target) != "ok":
                target.unlink(missing_ok=True)
                raise BackupError("La comprobación del respaldo SQLite no fue satisfactoria.")
            return target
        except (sqlite3.Error, OSError) as exc:
            target.unlink(missing_ok=True)
            raise BackupError(f"No se pudo crear el respaldo: {exc}") from exc

    def list_backups(self) -> list[BackupInfo]:
        if not self.backup_dir.exists():
            return []
        backups = []
        for path in self.backup_dir.iterdir():
            if not _BACKUP_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            backups.append(BackupInfo(path, stat.st_size, datetime.fromtimestamp(
                stat.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
                self.integrity_check(path)))
        return sorted(backups, key=lambda info: info.path.name, reverse=True)

    @staticmethod
    def integrity_check(path: Path | str) -> str:
        candidate = Path(path)
        try:
            connection = sqlite3.connect(f"{candidate.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
            try:
                rows = connection.execute("PRAGMA integrity_check").fetchall()
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return f"error: {exc}"
        if version < 1 or not rows:
            return "error: esquema SQLite no reconocido"
        return "ok" if len(rows) == 1 and rows[0][0] == "ok" else "; ".join(str(row[0]) for row in rows)

    def restore(self, backup_path: Path | str, *, confirm_overwrite: bool = False) -> RestoreResult:
        source = self._approved_backup(backup_path)
        integrity = self.integrity_check(source)
        if integrity != "ok":
            raise BackupError(f"El respaldo no pasó la comprobación de integridad: {integrity}")
        if not confirm_overwrite:
            raise BackupError("La restauración reemplaza la base actual. Confirma explícitamente la sobrescritura.")

        target = self.database.path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Se crea un respaldo de seguridad antes de cambiar el archivo activo.
        safety_copy = self.create_backup() if target.is_file() else None
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
        try:
            if target.is_file():
                with self.database.connect() as active:
                    checkpoint = active.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    if checkpoint and checkpoint[0]:
                        raise BackupError("La base está ocupada; cierra otras operaciones e inténtalo de nuevo.")
            with sqlite3.connect(source) as old, sqlite3.connect(temporary) as new:
                old.backup(new)
                new_version = int(new.execute("PRAGMA user_version").fetchone()[0])
                if new_version > CURRENT_SCHEMA_VERSION:
                    raise BackupError("El respaldo requiere una versión más reciente de la aplicación.")
                migrate(new)
            self._private(temporary, file=True)
            if self.integrity_check(temporary) != "ok":
                raise BackupError("La copia preparada para restauración no pasó la comprobación de integridad.")
            # WAL del archivo anterior no debe mezclarse con la base restaurada.
            Path(f"{target}-wal").unlink(missing_ok=True)
            Path(f"{target}-shm").unlink(missing_ok=True)
            os.replace(temporary, target)
            self._private(target, file=True)
        except (sqlite3.Error, OSError) as exc:
            temporary.unlink(missing_ok=True)
            detail = f" La copia de seguridad previa quedó en {safety_copy}." if safety_copy else ""
            raise BackupError(f"No se pudo restaurar el respaldo: {exc}.{detail}") from exc
        except BackupError as exc:
            temporary.unlink(missing_ok=True)
            detail = f" La base actual no se reemplazó y su respaldo de seguridad quedó en {safety_copy}." if safety_copy else ""
            raise BackupError(f"{exc}{detail}") from exc
        return RestoreResult(source, target, safety_copy)

    def _approved_backup(self, value: Path | str) -> Path:
        candidate = Path(value).expanduser()
        if candidate.is_symlink():
            raise BackupError("No se pueden restaurar enlaces simbólicos.")
        source = candidate.resolve()
        try:
            source.relative_to(self.backup_dir.resolve())
        except ValueError as exc:
            raise BackupError("Solo se pueden restaurar respaldos de la carpeta de respaldos de la aplicación.") from exc
        if source.is_symlink() or not source.is_file() or not _BACKUP_NAME.fullmatch(source.name):
            raise BackupError("El archivo seleccionado no es un respaldo válido de la aplicación.")
        return source

    @staticmethod
    def _new_name(prefix: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"

    @staticmethod
    def _private(path: Path, *, file: bool = False) -> None:
        try:
            path.chmod(0o600 if file else 0o700)
        except OSError:
            pass
