from __future__ import annotations

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.sanitization import escape_html, telephone_href
from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.patient_service import PatientService


@pytest.fixture
def service(tmp_path):
    repository = PatientRepository(initialize_database(tmp_path / "service.sqlite3"))
    return PatientService(repository), repository


def test_profile_is_private_by_default(service):
    patient_service, repository = service
    patient = patient_service.register({"full_name": "Ana Pérez", "blood_type": "O+"})
    assert patient.consent_json == "{}"
    assert patient_service.public_profile_data(patient.id) is None
    assert repository.consent_history(patient.id) == []


def test_consent_allows_only_selected_fields_and_is_audited(service):
    patient_service, repository = service
    patient = patient_service.register({
        "full_name": "Ana Pérez", "blood_type": "O+", "allergies": "Nueces",
        "additional_information": "Nota clínica interna",
    })
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name", "blood_type"],
        acknowledged=True, recorded_by="Paciente",
    )
    public = patient_service.public_profile_data(patient.id)
    assert public == {"full_name": "Ana Pérez", "blood_type": "O+", "uuid": patient.uuid}
    history = repository.consent_history(patient.id)
    assert len(history) == 1
    assert history[0]["granted"] == 1


def test_revocation_removes_public_projection_and_is_audited(service):
    patient_service, repository = service
    patient = patient_service.register({"full_name": "Ana Pérez"})
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name"], acknowledged=True
    )
    patient_service.set_consent(patient.id, granted=False, acknowledged=True)
    assert patient_service.public_profile_data(patient.id) is None
    history = repository.consent_history(patient.id)
    assert [event["granted"] for event in history] == [0, 1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"granted": True, "fields": ["full_name"], "acknowledged": False},
        {"granted": True, "fields": [], "acknowledged": True},
        {"granted": True, "fields": ["photo_path"], "acknowledged": True},
    ],
)
def test_consent_requires_explicit_acknowledgement_and_allowed_fields(service, kwargs):
    patient_service, _ = service
    patient = patient_service.register({"full_name": "Ana Pérez"})
    with pytest.raises(ValidationError):
        patient_service.set_consent(patient.id, **kwargs)


def test_consent_cannot_be_changed_through_generic_update(service):
    patient_service, _ = service
    patient = patient_service.register({"full_name": "Ana Pérez"})
    with pytest.raises(ValidationError):
        patient_service.update(patient.id, {"consent_json": '{"granted":true}'})


def test_html_and_phone_output_are_encoded_safely():
    assert escape_html('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
    assert telephone_href("+52 (55) 1234-5678") == "tel:+525512345678"
    with pytest.raises(ValidationError):
        telephone_href("javascript:alert(1)")


def test_validation_rejects_malformed_phone_and_control_chars(service):
    patient_service, _ = service
    with pytest.raises(ValidationError):
        patient_service.register({"full_name": "Ana", "emergency_contact_phone": "123"})
    with pytest.raises(ValidationError):
        patient_service.register({"full_name": "Ana\x00Perez"})
