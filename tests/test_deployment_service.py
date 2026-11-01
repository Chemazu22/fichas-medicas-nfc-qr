from __future__ import annotations

import shutil
import subprocess

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.deployment_service import DeploymentError, DeploymentService
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.profile_service import ProfileService
from fichas_medicas.services.publication_state import PublicationStateStore


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git no está instalado")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def setup_services(tmp_path):
    repo_dir = tmp_path / "pages-repo"
    repo_dir.mkdir()
    git("init", "-b", "main", cwd=repo_dir)
    git("config", "user.name", "Fichas Test", cwd=repo_dir)
    git("config", "user.email", "fichas-test@example.invalid", cwd=repo_dir)
    git("remote", "add", "origin", "https://github.com/example/medical-pages.git", cwd=repo_dir)
    (repo_dir / "README.md").write_text("Pages repo\n")
    git("add", "README.md", cwd=repo_dir)
    git("commit", "-m", "Initial commit", cwd=repo_dir)

    database = initialize_database(tmp_path / "application.sqlite3")
    patients = PatientService(PatientRepository(database))
    profiles = ProfileService(patients, tmp_path / "generated-profiles")
    deployment = DeploymentService(repo_dir, profiles, publication_state=PublicationStateStore(tmp_path / "publication-state.json"))
    deployment._push = lambda: None
    return repo_dir, patients, profiles, deployment


def test_deployment_commits_only_consenting_profile_files(tmp_path):
    repo_dir, patients, _, deployment = setup_services(tmp_path)
    patient = patients.register({"full_name": "Ana Pérez", "allergies": "Nueces"})
    patients.set_consent(patient.id, granted=True, fields=["full_name"], acknowledged=True)
    result = deployment.publish()
    assert result.status == "published"
    assert f"{patient.uuid}.html" in result.files
    assert (repo_dir / f"{patient.uuid}.html").exists()
    assert "Nueces" not in (repo_dir / f"{patient.uuid}.html").read_text()
    assert (repo_dir / "styles.css").exists()
    assert deployment.publication_state.get(patient.uuid) == "published"


def test_deployment_removes_profile_after_consent_revocation(tmp_path):
    repo_dir, patients, _, deployment = setup_services(tmp_path)
    patient = patients.register({"full_name": "Ana Pérez"})
    patients.set_consent(patient.id, granted=True, fields=["full_name"], acknowledged=True)
    deployment.publish()
    profile_path = repo_dir / f"{patient.uuid}.html"
    assert profile_path.exists()
    patients.set_consent(patient.id, granted=False, acknowledged=True)
    result = deployment.publish()
    assert result.status == "published"
    assert not profile_path.exists()
    assert not (repo_dir / "styles.css").exists()
    assert deployment.publication_state.get(patient.uuid) == "removed"


def test_deployment_never_publishes_unmatched_local_uuid_artifacts(tmp_path):
    repo_dir, _, profiles, deployment = setup_services(tmp_path)
    orphan = profiles.output_dir / "12345678-1234-4234-8234-123456789abc.html"
    profiles.output_dir.mkdir(parents=True, exist_ok=True)
    orphan.write_text("stale private artifact", encoding="utf-8")

    result = deployment.publish()

    assert result.status == "no_changes"
    assert not orphan.exists()
    assert not (repo_dir / orphan.name).exists()


def test_failed_push_keeps_local_commit_and_can_be_retried(tmp_path):
    repo_dir, patients, _, deployment = setup_services(tmp_path)
    patient = patients.register({"full_name": "Ana Pérez"})
    patients.set_consent(patient.id, granted=True, fields=["full_name"], acknowledged=True)
    deployment._push = lambda: (_ for _ in ()).throw(DeploymentError("Sin conexión"))
    failed = deployment.publish()
    assert failed.status == "push_failed"
    assert failed.commit
    assert (repo_dir / f"{patient.uuid}.html").exists()
    deployment._push = lambda: None
    assert deployment.retry_push().status == "pushed"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:token@github.com/example/repo.git",
        "https://github.com/example/repo.git?token=secret",
        "file:///tmp/pages.git",
        "http://github.com/example/repo.git",
    ],
)
def test_remote_url_rejects_credentials_and_unsafe_schemes(url):
    with pytest.raises(ValidationError):
        DeploymentService.validate_remote_url(url)
