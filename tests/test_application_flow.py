from __future__ import annotations

import shutil
import subprocess

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.services.backup_service import BackupService
from fichas_medicas.services.deployment_service import DeploymentService
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.profile_service import ProfileService
from fichas_medicas.services.publication_state import PublicationStateStore
from fichas_medicas.services.qr_service import QrService
from fichas_medicas.security.validation import ValidationError


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git no está instalado")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_synthetic_patient_consent_qr_publish_revoke_and_restore(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    git("init", "-b", "main", cwd=pages)
    git("config", "user.name", "Fichas Test", cwd=pages)
    git("config", "user.email", "fichas-test@example.invalid", cwd=pages)
    git("remote", "add", "origin", "https://github.com/example/pages.git", cwd=pages)
    (pages / "README.md").write_text("Pages de prueba\n", encoding="utf-8")
    git("add", "README.md", cwd=pages)
    git("commit", "-m", "Initial test commit", cwd=pages)

    database = initialize_database(tmp_path / "private" / "app.sqlite3")
    patients = PatientService(PatientRepository(database))
    profiles = ProfileService(patients, tmp_path / "private" / "profiles")
    qr = QrService(patients, "https://demo.example.invalid/medical/", tmp_path / "private" / "qr")
    backups = BackupService(database, tmp_path / "private" / "backups")
    publication = PublicationStateStore(tmp_path / "private" / "publication-state.json")
    deployment = DeploymentService(pages, profiles, publication_state=publication)
    deployment._push = lambda: None  # Nunca conecta a un remoto durante esta prueba.

    patient = patients.register({
        "full_name": "Paciente ficticio E2E",
        "blood_type": "O+",
        "allergies": "Alergia sintética de prueba",
        "medications": "Dato no consentido que no debe salir",
    })
    assert patients.public_profile_data(patient.id) is None
    assert profiles.generate(patient.id) is None
    assert qr.generate_for_patient(patient.id) is None
    with pytest.raises(ValidationError):
        qr.nfc_payload(patient.id)

    patients.set_consent(
        patient.id,
        granted=True,
        fields=["full_name", "blood_type", "allergies"],
        acknowledged=True,
        recorded_by="Prueba sintética",
    )
    profile = profiles.generate(patient.id)
    qr_png = qr.generate_for_patient(patient.id)
    payload = qr.nfc_payload(patient.id)
    assert profile and profile.exists()
    assert "Paciente ficticio E2E" in profile.read_text(encoding="utf-8")
    assert "Alergia sintética de prueba" in profile.read_text(encoding="utf-8")
    assert "Dato no consentido" not in profile.read_text(encoding="utf-8")
    assert qr_png and qr_png.exists() and qr_png.stat().st_size > 0
    assert payload == f"https://demo.example.invalid/medical/{patient.uuid}.html"

    prior_consent_backup = backups.create_backup()
    published = deployment.publish()
    remote_profile = pages / f"{patient.uuid}.html"
    assert published.status == "published"
    assert remote_profile.exists()

    patients.set_consent(patient.id, granted=False, acknowledged=True, note="Revocación ficticia")
    profiles.remove(patient.id)
    qr.remove_for_patient(patient.id)
    removal = deployment.publish()
    assert removal.status == "published"
    assert not profile.exists()
    assert not qr_png.exists()
    assert not remote_profile.exists()

    backups.restore(prior_consent_backup, confirm_overwrite=True)
    restored_patient = patients.repository.get(patient.id)
    assert restored_patient.consent_json == "{}"
    assert patients.public_profile_data(patient.id) is None
    assert profiles.generate(patient.id) is None
    assert qr.generate_for_patient(patient.id) is None
