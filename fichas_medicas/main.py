"""Punto de entrada para iniciar la aplicación de escritorio."""

from __future__ import annotations

from fichas_medicas.config.app_settings import AppSettings
from fichas_medicas.database.connection import initialize_database
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.profile_service import ProfileService


def main() -> None:
    try:
        import customtkinter
    except ImportError as exc:
        raise RuntimeError("CustomTkinter no está instalado. Ejecuta: python -m pip install -r requirements.txt") from exc
    from fichas_medicas.ui.application import MedicalRecordsApp

    database = initialize_database()
    repository = PatientRepository(database)
    patients = PatientService(repository)
    profiles = ProfileService(patients)
    settings = AppSettings()
    app = MedicalRecordsApp(repository, patients, profiles, settings)
    app.mainloop()


if __name__ == "__main__":
    main()
