"""Validaciones de dominio para datos de personas."""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Any

ALLOWED_BLOOD_TYPES = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Desconocido"}
TEXT_LIMITS = {
    "full_name": 200,
    "allergies": 10_000,
    "conditions": 10_000,
    "medications": 10_000,
    "additional_information": 20_000,
    "emergency_contact_name": 200,
    "emergency_contact_relationship": 100,
    "emergency_contact_phone": 40,
    "emergency_contact_2_name": 200,
    "emergency_contact_2_relationship": 100,
    "emergency_contact_2_phone": 40,
    "emergency_contact_3_name": 200,
    "emergency_contact_3_relationship": 100,
    "emergency_contact_3_phone": 40,
    "photo_path": 2_000,
}
DEFAULTS = {"allergies": "", "conditions": "", "medications": "",
            "additional_information": "", "emergency_contact_name": "",
            "emergency_contact_relationship": "", "emergency_contact_phone": "",
            "emergency_contact_2_name": "", "emergency_contact_2_relationship": "",
            "emergency_contact_2_phone": "", "emergency_contact_3_name": "",
            "emergency_contact_3_relationship": "", "emergency_contact_3_phone": "",
            "photo_path": None, "consent_json": "{}", "status": "active"}
FIELDS = set(TEXT_LIMITS) | {"date_of_birth", "blood_type", "consent_json", "status"}
PHONE_PATTERN = re.compile(r"^[0-9+().\-\s]*$")


class ValidationError(ValueError):
    """Entrada que no cumple las reglas del dominio."""


def validate_patient(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    unknown = set(data) - FIELDS
    if unknown:
        raise ValidationError(f"Campos no reconocidos: {', '.join(sorted(unknown))}")
    if not partial and "full_name" not in data:
        raise ValidationError("El nombre completo es obligatorio.")
    result = dict(data)
    if not partial:
        for key, value in DEFAULTS.items():
            result.setdefault(key, value)
    if "full_name" in result:
        value = result["full_name"]
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("El nombre completo es obligatorio.")
        result["full_name"] = value.strip()
    for field, limit in TEXT_LIMITS.items():
        if field not in result or result[field] is None:
            continue
        value = result[field]
        if not isinstance(value, str):
            raise ValidationError(f"{field} debe ser texto.")
        result[field] = value.strip() if field == "emergency_contact_phone" else value.strip()
        if len(result[field]) > limit:
            raise ValidationError(f"{field} supera el máximo de {limit} caracteres.")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in result[field]):
            raise ValidationError(f"{field} contiene caracteres de control no permitidos.")
    for field in ("emergency_contact_phone", "emergency_contact_2_phone", "emergency_contact_3_phone"):
        if result.get(field):
            phone = result[field]
            digits = sum(char.isdigit() for char in phone)
            if not PHONE_PATTERN.fullmatch(phone) or not 7 <= digits <= 15:
                raise ValidationError("Cada teléfono de emergencia debe contener entre 7 y 15 dígitos.")
    if "date_of_birth" in result and result["date_of_birth"] not in (None, ""):
        if not isinstance(result["date_of_birth"], str):
            raise ValidationError("La fecha de nacimiento debe usar AAAA-MM-DD.")
        try:
            parsed = date.fromisoformat(result["date_of_birth"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("La fecha de nacimiento debe usar AAAA-MM-DD.") from exc
        if parsed > date.today():
            raise ValidationError("La fecha de nacimiento no puede estar en el futuro.")
    if "blood_type" in result and result["blood_type"] not in (None, "", *ALLOWED_BLOOD_TYPES):
        raise ValidationError("Tipo de sangre no válido.")
    if result.get("blood_type") == "":
        result["blood_type"] = None
    if "status" in result and result["status"] not in {"active", "archived", "deleted"}:
        raise ValidationError("Estado de expediente no válido.")
    if "consent_json" in result:
        if not isinstance(result["consent_json"], str):
            raise ValidationError("consent_json debe ser texto JSON.")
        try:
            consent = json.loads(result["consent_json"])
        except (ValueError, TypeError) as exc:
            raise ValidationError("consent_json no contiene JSON válido.") from exc
        if not isinstance(consent, dict):
            raise ValidationError("consent_json debe ser un objeto JSON.")
    return result
