"""Operaciones parametrizadas para expedientes médicos."""

from __future__ import annotations

import json
import sqlite3
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any

from fichas_medicas.database.connection import Database
from fichas_medicas.database.models import Patient
from fichas_medicas.security.validation import FIELDS, ValidationError, validate_patient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _patient(row: sqlite3.Row) -> Patient:
    return Patient(**dict(row))


class PatientRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, data: dict[str, Any]) -> Patient:
        values = validate_patient(data)
        # Consentimiento es un objeto JSON; validarlo evita guardar texto mal formado.
        try:
            decoded = json.loads(values["consent_json"])
        except json.JSONDecodeError as exc:
            raise ValidationError("consent_json no contiene JSON válido.") from exc
        if not isinstance(decoded, dict):
            raise ValidationError("consent_json debe ser un objeto JSON.")
        values["consent_json"] = json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
        now = _now()
        patient_uuid = str(uuid_module.uuid4())
        columns = ["uuid", *values.keys(), "created_at", "updated_at"]
        params = [patient_uuid, *values.values(), now, now]
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO patients ({', '.join(columns)}) VALUES ({placeholders})"
        with self.database.connect() as connection:
            cursor = connection.execute(sql, params)
            row = connection.execute("SELECT * FROM patients WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _patient(row)

    def get(self, patient_id: int) -> Patient | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM patients WHERE id = ? AND status != 'deleted'", (patient_id,)
            ).fetchone()
        return _patient(row) if row else None

    def get_by_uuid(self, patient_uuid: str) -> Patient | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM patients WHERE uuid = ? AND status != 'deleted'", (patient_uuid,)
            ).fetchone()
        return _patient(row) if row else None

    def update(self, patient_id: int, changes: dict[str, Any]) -> Patient:
        changes = dict(changes)
        changes.pop("id", None)
        changes.pop("uuid", None)
        changes.pop("created_at", None)
        changes.pop("updated_at", None)
        changes.pop("status", None)  # Los cambios de estado tienen una operación explícita.
        if not changes:
            patient = self.get(patient_id)
            if patient is None:
                raise KeyError(f"Expediente {patient_id} no encontrado.")
            return patient
        values = validate_patient(changes, partial=True)
        if "consent_json" in values:
            try:
                consent = json.loads(values["consent_json"])
            except json.JSONDecodeError as exc:
                raise ValidationError("consent_json no contiene JSON válido.") from exc
            if not isinstance(consent, dict):
                raise ValidationError("consent_json debe ser un objeto JSON.")
            values["consent_json"] = json.dumps(consent, ensure_ascii=False, separators=(",", ":"))
        unknown = set(values) - FIELDS
        if unknown:
            raise ValidationError(f"Campos no reconocidos: {', '.join(sorted(unknown))}")
        values["updated_at"] = _now()
        assignments = ", ".join(f"{column} = ?" for column in values)
        params = [*values.values(), patient_id]
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE patients SET {assignments} WHERE id = ? AND status != 'deleted'", params
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Expediente {patient_id} no encontrado.")
            row = connection.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return _patient(row)

    def set_status(self, patient_id: int, status: str) -> Patient:
        if status not in {"active", "archived"}:
            raise ValidationError("El estado debe ser active o archived.")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE patients SET status = ?, updated_at = ? WHERE id = ? AND status != 'deleted'",
                (status, _now(), patient_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Expediente {patient_id} no encontrado.")
            row = connection.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return _patient(row)

    def record_consent(
        self,
        patient_id: int,
        *,
        consent_json: str,
        granted: bool,
        fields: list[str],
        recorded_by: str = "",
        note: str = "",
    ) -> Patient:
        """Actualiza el estado vigente y agrega el evento de auditoría atómicamente."""
        now = _now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE patients SET consent_json = ?, updated_at = ? "
                "WHERE id = ? AND status != 'deleted'",
                (consent_json, now, patient_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Expediente {patient_id} no encontrado.")
            connection.execute(
                "INSERT INTO consent_events "
                "(patient_id, granted, public_fields_json, recorded_at, recorded_by, note) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (patient_id, int(granted), json.dumps(fields), now, recorded_by, note),
            )
            row = connection.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return _patient(row)

    def consent_history(self, patient_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, granted, public_fields_json, recorded_at, recorded_by, note "
                "FROM consent_events WHERE patient_id = ? ORDER BY id DESC",
                (patient_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, patient_id: int) -> None:
        """Eliminación lógica: preserva integridad operativa y marca el registro como eliminado."""
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE patients SET status = 'deleted', updated_at = ? "
                "WHERE id = ? AND status != 'deleted'",
                (_now(), patient_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Expediente {patient_id} no encontrado.")

    def search(self, query: str = "", *, include_archived: bool = False, limit: int = 100) -> list[Patient]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit debe estar entre 1 y 1000.")
        status_clause = "status != 'deleted'" if include_archived else "status = 'active'"
        pattern = f"%{query.strip()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM patients WHERE {status_clause} AND full_name LIKE ? COLLATE NOCASE "
                "ORDER BY full_name COLLATE NOCASE LIMIT ?",
                (pattern, limit),
            ).fetchall()
        return [_patient(row) for row in rows]

    def list_all(self, *, include_deleted: bool = False, offset: int = 0, limit: int = 500) -> list[Patient]:
        """Lista expedientes paginados para tareas administrativas internas."""
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset debe ser >= 0 y limit debe estar entre 1 y 1000.")
        where = "" if include_deleted else "WHERE status != 'deleted'"
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM patients {where} ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_patient(row) for row in rows]
