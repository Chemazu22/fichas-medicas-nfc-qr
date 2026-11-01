"""Reglas de negocio para expedientes y consentimiento de publicación."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from fichas_medicas.database.models import Patient
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.validation import ValidationError

PUBLIC_FIELDS = frozenset({
    "full_name",
    "date_of_birth",
    "blood_type",
    "allergies",
    "conditions",
    "medications",
    "additional_information",
    "emergency_contact_name",
    "emergency_contact_relationship",
    "emergency_contact_phone",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PatientService:
    """Capa de aplicación: valida operaciones y nunca asume consentimiento."""

    def __init__(self, repository: PatientRepository) -> None:
        self.repository = repository

    def register(self, data: dict[str, Any]) -> Patient:
        # No se acepta que el formulario de alta autorice publicación indirectamente.
        safe_data = dict(data)
        safe_data.pop("consent_json", None)
        return self.repository.create(safe_data)

    def update(self, patient_id: int, changes: dict[str, Any]) -> Patient:
        if "consent_json" in changes:
            raise ValidationError("Usa set_consent para cambiar el consentimiento y conservar auditoría.")
        return self.repository.update(patient_id, changes)

    def delete(self, patient_id: int) -> None:
        self.repository.delete(patient_id)

    def search(self, query: str = "", *, include_archived: bool = False, limit: int = 100) -> list[Patient]:
        return self.repository.search(query, include_archived=include_archived, limit=limit)

    def set_consent(
        self,
        patient_id: int,
        *,
        granted: bool,
        fields: Iterable[str] = (),
        acknowledged: bool,
        recorded_by: str = "",
        note: str = "",
    ) -> Patient:
        """Registra o revoca consentimiento con auditoría. Aceptación debe ser explícita."""
        if not isinstance(acknowledged, bool) or not acknowledged:
            raise ValidationError("Se requiere confirmación explícita del consentimiento.")
        if not isinstance(granted, bool):
            raise ValidationError("granted debe ser verdadero o falso.")
        if not isinstance(recorded_by, str) or len(recorded_by) > 200:
            raise ValidationError("recorded_by debe ser texto de hasta 200 caracteres.")
        if not isinstance(note, str) or len(note) > 2000:
            raise ValidationError("note debe ser texto de hasta 2000 caracteres.")
        if isinstance(fields, (str, bytes)):
            raise ValidationError("fields debe ser una lista de nombres de campo.")
        try:
            selected = set(fields)
        except TypeError as exc:
            raise ValidationError("fields contiene valores no válidos.") from exc
        if any(not isinstance(field, str) for field in selected):
            raise ValidationError("Cada campo de consentimiento debe ser texto.")
        unknown = selected - PUBLIC_FIELDS
        if unknown:
            raise ValidationError(f"Campos no publicables: {', '.join(sorted(unknown))}")
        if granted and not selected:
            raise ValidationError("Selecciona al menos un campo autorizado para publicar.")
        if not granted:
            selected.clear()
        patient = self.repository.get(patient_id)
        if patient is None:
            raise KeyError(f"Expediente {patient_id} no encontrado.")
        consent = {
            "version": 1,
            "granted": granted,
            "fields": sorted(selected),
            "recorded_at": _utc_now(),
        }
        updated = self.repository.record_consent(
            patient_id,
            consent_json=json.dumps(consent, ensure_ascii=False, separators=(",", ":")),
            granted=granted,
            fields=sorted(selected),
            recorded_by=recorded_by.strip(),
            note=note.strip(),
        )
        return updated

    def public_profile_data(self, patient_id: int) -> dict[str, Any] | None:
        """Devuelve solo la proyección consentida; None si no hay autorización vigente."""
        patient = self.repository.get(patient_id)
        if patient is None or patient.status != "active":
            return None
        try:
            consent = json.loads(patient.consent_json)
        except (TypeError, ValueError):
            return None
        if not isinstance(consent, dict):
            return None
        if type(consent.get("version")) is not int or consent.get("version") != 1:
            return None
        if consent.get("granted") is not True:
            return None
        fields = consent.get("fields")
        if (
            not isinstance(fields, list)
            or any(not isinstance(field, str) for field in fields)
            or set(fields) - PUBLIC_FIELDS
        ):
            return None
        data = {field: getattr(patient, field) for field in fields}
        data["uuid"] = patient.uuid
        return data
