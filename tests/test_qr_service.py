from __future__ import annotations

import importlib.util

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.qr_service import QrService


def setup_services(tmp_path, base_url="https://medical.example.org/cards/"):
    repository = PatientRepository(initialize_database(tmp_path / "qr.sqlite3"))
    patient_service = PatientService(repository)
    qr_service = QrService(patient_service, base_url, tmp_path / "qr-output")
    return repository, patient_service, qr_service


def test_builds_public_url_with_uuid_filename(tmp_path):
    _, _, service = setup_services(tmp_path, "https://owner.github.io/medical-cards/")
    patient_uuid = "3f6b2eb8-1350-4e78-a025-2c0f4e622924"
    assert service.build_profile_url(patient_uuid) == (
        "https://owner.github.io/medical-cards/3f6b2eb8-1350-4e78-a025-2c0f4e622924.html"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.org/cards",
        "https://user:password@example.org/cards",
        "https://example.org/cards?token=secret",
        "https://example.org/cards#fragment",
        "https://example.org/../private",
    ],
)
def test_rejects_unsafe_or_malformed_base_urls(tmp_path, base_url):
    repository = PatientRepository(initialize_database(tmp_path / "invalid.sqlite3"))
    patient_service = PatientService(repository)
    with pytest.raises(ValidationError):
        QrService(patient_service, base_url, tmp_path / "qr-output")


def test_nfc_payload_is_the_same_https_url_and_requires_consent(tmp_path):
    _, patient_service, service = setup_services(tmp_path)
    patient = patient_service.register({"full_name": "Ana Pérez"})
    with pytest.raises(ValidationError):
        service.nfc_payload(patient.id)
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name"], acknowledged=True
    )
    assert service.nfc_payload(patient.id) == service.build_profile_url(patient.uuid)


@pytest.mark.skipif(importlib.util.find_spec("qrcode") is None, reason="Instala requirements.txt para generar PNG QR")
def test_generates_png_qr_only_for_consented_patient(tmp_path):
    _, patient_service, service = setup_services(tmp_path)
    patient = patient_service.register({"full_name": "Ana Pérez"})
    assert service.generate_for_patient(patient.id) is None
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name"], acknowledged=True
    )
    path = service.generate_for_patient(patient.id)
    assert path is not None and path.name == f"{patient.uuid}.png"
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
