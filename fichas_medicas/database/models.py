"""Tipos de datos de la capa de persistencia."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Patient:
    id: int
    uuid: str
    full_name: str
    date_of_birth: str | None
    blood_type: str | None
    allergies: str
    conditions: str
    medications: str
    additional_information: str
    emergency_contact_name: str
    emergency_contact_relationship: str
    emergency_contact_phone: str
    photo_path: str | None
    consent_json: str
    created_at: str
    updated_at: str
    status: str
