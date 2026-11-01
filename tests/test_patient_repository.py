from __future__ import annotations

from datetime import date, timedelta

import pytest

from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.validation import ValidationError


@pytest.fixture
def repository(tmp_path):
    database = initialize_database(tmp_path / "test.sqlite3")
    return PatientRepository(database)


def test_create_generates_uuid_and_timestamps(repository):
    patient = repository.create({"full_name": "  Ana Pérez  ", "blood_type": "O+"})
    assert patient.full_name == "Ana Pérez"
    assert len(patient.uuid) == 36
    assert patient.created_at == patient.updated_at
    assert patient.status == "active"
    assert repository.get_by_uuid(patient.uuid) == patient


def test_update_preserves_id_and_changes_updated_timestamp(repository):
    patient = repository.create({"full_name": "Ana Pérez"})
    updated = repository.update(patient.id, {"allergies": "Penicilina"})
    assert updated.id == patient.id
    assert updated.uuid == patient.uuid
    assert updated.allergies == "Penicilina"
    assert updated.updated_at >= patient.updated_at


def test_search_and_soft_delete(repository):
    ana = repository.create({"full_name": "Ana Pérez"})
    repository.create({"full_name": "Luis Gómez"})
    assert [p.full_name for p in repository.search("pérez")] == ["Ana Pérez"]
    repository.delete(ana.id)
    assert repository.get(ana.id) is None
    assert repository.search("Ana") == []


def test_archive_is_excluded_by_default(repository):
    patient = repository.create({"full_name": "Luis Gómez"})
    repository.set_status(patient.id, "archived")
    assert repository.search("Luis") == []
    assert len(repository.search("Luis", include_archived=True)) == 1


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"full_name": "  "},
        {"full_name": "Ana", "blood_type": "X"},
        {"full_name": "Ana", "date_of_birth": (date.today() + timedelta(days=1)).isoformat()},
        {"full_name": "Ana', DROP TABLE patients; --", "unexpected": "x"},
    ],
)
def test_invalid_data_is_rejected(repository, record):
    with pytest.raises(ValidationError):
        repository.create(record)


def test_sql_like_input_is_treated_as_search_text(repository):
    repository.create({"full_name": "Ana Pérez"})
    assert repository.search("%' OR 1=1 --") == []


def test_database_file_has_private_permissions(tmp_path):
    database_path = tmp_path / "private" / "db.sqlite3"
    initialize_database(database_path)
    assert database_path.exists()
    assert database_path.stat().st_mode & 0o777 == 0o600
