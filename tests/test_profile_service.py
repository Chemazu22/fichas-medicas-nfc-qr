from __future__ import annotations

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.profile_service import ProfileService


def setup_services(tmp_path):
    repository = PatientRepository(initialize_database(tmp_path / "profiles.sqlite3"))
    patient_service = PatientService(repository)
    profile_service = ProfileService(patient_service, tmp_path / "public-output")
    return repository, patient_service, profile_service


def test_generates_responsive_profile_from_consented_projection(tmp_path):
    _, patient_service, profile_service = setup_services(tmp_path)
    patient = patient_service.register({
        "full_name": "Ana <script>alert(1)</script>",
        "blood_type": "O+",
        "allergies": "Nueces & cacahuate",
        "emergency_contact_name": "Luis Pérez",
        "emergency_contact_relationship": "Hermano",
        "emergency_contact_phone": "+52 (55) 1234-5678",
    })
    patient_service.set_consent(
        patient.id,
        granted=True,
        fields=["full_name", "blood_type", "allergies", "emergency_contact_name",
                "emergency_contact_relationship", "emergency_contact_phone"],
        acknowledged=True,
    )

    path = profile_service.generate(patient.id)
    assert path is not None and path.name == f"{patient.uuid}.html"
    html = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Nueces &amp; cacahuate" in html
    assert 'href="tel:+525512345678"' in html
    assert "noindex, nofollow" in html
    assert (path.parent / "styles.css").exists()


def test_profile_is_not_generated_without_consent(tmp_path):
    _, patient_service, profile_service = setup_services(tmp_path)
    patient = patient_service.register({"full_name": "Ana Pérez"})
    assert profile_service.generate(patient.id) is None
    assert not list((tmp_path / "public-output").glob("*.html"))


def test_revoking_consent_removes_existing_local_profile(tmp_path):
    _, patient_service, profile_service = setup_services(tmp_path)
    patient = patient_service.register({"full_name": "Ana Pérez"})
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name"], acknowledged=True
    )
    generated = profile_service.generate(patient.id)
    assert generated is not None and generated.exists()
    patient_service.set_consent(patient.id, granted=False, acknowledged=True)
    assert profile_service.generate(patient.id) is None
    assert not generated.exists()


def test_delete_removes_profile_for_logically_deleted_patient(tmp_path):
    _, patient_service, profile_service = setup_services(tmp_path)
    patient = patient_service.register({"full_name": "Ana Pérez"})
    patient_service.set_consent(
        patient.id, granted=True, fields=["full_name"], acknowledged=True
    )
    generated = profile_service.generate(patient.id)
    patient_service.delete(patient.id)
    assert profile_service.remove(patient.id)
    assert not generated.exists()
