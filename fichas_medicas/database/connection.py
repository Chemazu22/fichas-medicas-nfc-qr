"""Administración de conexiones y transacciones SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fichas_medicas.config.paths import database_path, ensure_data_directory
from fichas_medicas.database.migrations import migrate


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else database_path()

    def initialize(self) -> None:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                pass
        with self.connect() as connection:
            migrate(connection)
        if self.path.exists():
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if str(self.path) != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        return connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transacción explícita; hace rollback completo ante cualquier excepción."""
        with self.connect() as connection:
            connection.execute("BEGIN")
            yield connection


def initialize_database(path: Path | str | None = None) -> Database:
    """Crea rutas y esquema; retorna el objeto listo para usar."""
    if path is None:
        ensure_data_directory()
    database = Database(path)
    database.initialize()
    return database
