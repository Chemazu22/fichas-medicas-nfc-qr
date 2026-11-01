"""Migraciones del esquema SQLite, versionadas con PRAGMA user_version."""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 2

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL CHECK (length(trim(full_name)) BETWEEN 1 AND 200),
            date_of_birth TEXT,
            blood_type TEXT CHECK (blood_type IS NULL OR blood_type IN
                ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Desconocido')),
            allergies TEXT NOT NULL DEFAULT '',
            conditions TEXT NOT NULL DEFAULT '',
            medications TEXT NOT NULL DEFAULT '',
            additional_information TEXT NOT NULL DEFAULT '',
            emergency_contact_name TEXT NOT NULL DEFAULT '',
            emergency_contact_relationship TEXT NOT NULL DEFAULT '',
            emergency_contact_phone TEXT NOT NULL DEFAULT '',
            photo_path TEXT,
            consent_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived', 'deleted'))
        )""",
        "CREATE INDEX idx_patients_full_name ON patients(full_name COLLATE NOCASE)",
        "CREATE INDEX idx_patients_status_updated ON patients(status, updated_at DESC)",
    ),
    2: (
        """CREATE TABLE consent_events (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
            public_fields_json TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            recorded_by TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT ''
        )""",
        "CREATE INDEX idx_consent_events_patient_time ON consent_events(patient_id, recorded_at DESC)",
    ),
}


def migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"La base usa el esquema {version}, superior al compatible "
            f"({CURRENT_SCHEMA_VERSION}). Actualiza la aplicación."
        )
    for target_version in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
        statements = _MIGRATIONS.get(target_version)
        if statements is None:
            raise RuntimeError(f"No existe migración para el esquema {target_version}.")
        with connection:
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {target_version}")
