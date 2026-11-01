from __future__ import annotations

import sqlite3

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.services.backup_service import BackupError, BackupService
from fichas_medicas.services.patient_service import PatientService


def setup(tmp_path):
    database = initialize_database(tmp_path / "app.sqlite3")
    patients = PatientService(PatientRepository(database))
    backups = BackupService(database, tmp_path / "private-backups")
    return database, patients, backups


def test_backup_is_consistent_and_listed(tmp_path):
    _, patients, backups = setup(tmp_path)
    patient = patients.register({"full_name": "Ana Pérez"})

    path = backups.create_backup()

    assert path.parent == tmp_path / "private-backups"
    assert path.stat().st_mode & 0o777 == 0o600
    assert backups.integrity_check(path) == "ok"
    listed = backups.list_backups()
    assert len(listed) == 1
    assert listed[0].path == path
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT full_name FROM patients").fetchone()[0] == "Ana Pérez"


def test_restore_requires_confirmation_and_keeps_safety_backup(tmp_path):
    database, patients, backups = setup(tmp_path)
    patient = patients.register({"full_name": "Ana Pérez"})
    backup = backups.create_backup()
    patients.update(patient.id, {"full_name": "Nombre posterior"})

    with pytest.raises(BackupError, match="Confirma explícitamente"):
        backups.restore(backup)
    result = backups.restore(backup, confirm_overwrite=True)

    assert patients.repository.get(patient.id).full_name == "Ana Pérez"
    assert result.restored_from == backup
    assert result.database_path == database.path
    assert result.safety_backup is not None and result.safety_backup.exists()
    with sqlite3.connect(result.safety_backup) as connection:
        assert connection.execute("SELECT full_name FROM patients").fetchone()[0] == "Nombre posterior"
    assert database.path.exists()


def test_restore_rejects_unlisted_or_corrupt_backup(tmp_path):
    _, _, backups = setup(tmp_path)
    outside = tmp_path / "outside.sqlite3"
    sqlite3.connect(outside).close()
    with pytest.raises(BackupError, match="carpeta de respaldos"):
        backups.restore(outside, confirm_overwrite=True)

    corrupt = backups.backup_dir / "backup-20261031T120000Z-12345678.sqlite3"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(BackupError, match="integridad"):
        backups.restore(corrupt, confirm_overwrite=True)
