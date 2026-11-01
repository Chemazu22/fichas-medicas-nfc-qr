"""Construcción de URL pública, generación QR y payload URL para NFC/NDEF."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fichas_medicas.config.paths import qr_directory
from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.patient_service import PatientService

UUID_V4_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class QrService:
    def __init__(
        self,
        patient_service: PatientService,
        public_base_url: str | None = None,
        output_dir: Path | str | None = None,
    ) -> None:
        self.patient_service = patient_service
        configured_url = public_base_url or os.environ.get("FICHAS_MEDICAS_PUBLIC_BASE_URL")
        if not configured_url:
            raise ValidationError(
                "Configura FICHAS_MEDICAS_PUBLIC_BASE_URL con la URL HTTPS pública de GitHub Pages."
            )
        self.public_base_url = self._validate_base_url(configured_url)
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else qr_directory()

    @staticmethod
    def _validate_base_url(value: str) -> str:
        if not isinstance(value, str) or value != value.strip() or any(char.isspace() for char in value):
            raise ValidationError("La URL base debe ser una URL HTTPS válida sin espacios.")
        try:
            parsed = urlsplit(value)
            hostname = parsed.hostname
            _ = parsed.port  # Fuerza validación de puertos inválidos.
        except ValueError as exc:
            raise ValidationError("La URL base contiene una autoridad o puerto inválido.") from exc
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in parsed.path
            or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        ):
            raise ValidationError("La URL base debe ser HTTPS pública y no contener credenciales, query ni fragmento.")
        path = parsed.path.rstrip("/") + "/"
        return urlunsplit(("https", parsed.netloc, path, "", ""))

    def build_profile_url(self, patient_uuid: str) -> str:
        if not isinstance(patient_uuid, str) or not UUID_V4_PATTERN.fullmatch(patient_uuid):
            raise ValidationError("Se requiere un UUIDv4 válido para construir la URL.")
        return f"{self.public_base_url}{patient_uuid}.html"

    def nfc_payload(self, patient_id: int) -> str:
        """Devuelve la URL que un programador compatible debe escribir en un registro NDEF URI."""
        patient = self.patient_service.repository.get(patient_id)
        if patient is None or self.patient_service.public_profile_data(patient_id) is None:
            raise ValidationError("El expediente no tiene un perfil activo con consentimiento vigente.")
        return self.build_profile_url(patient.uuid)

    def generate_for_patient(self, patient_id: int) -> Path | None:
        """Genera un PNG QR solo si el expediente está activo y autorizado para publicar."""
        patient = self.patient_service.repository.get(patient_id)
        if patient is None:
            raise KeyError(f"Expediente {patient_id} no encontrado.")
        target = self.output_dir / f"{patient.uuid}.png"
        if self.patient_service.public_profile_data(patient_id) is None:
            target.unlink(missing_ok=True)
            return None
        url = self.build_profile_url(patient.uuid)
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_Q
        except ImportError as exc:
            raise RuntimeError(
                "Falta la biblioteca qrcode. Instálala con: python -m pip install -r requirements.txt"
            ) from exc

        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_Q,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")

        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.output_dir.chmod(0o700)
        except OSError:
            pass
        temporary = target.with_suffix(".png.tmp")
        image.save(temporary, format="PNG")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(target)
        return target

    def remove_for_patient(self, patient_id: int) -> bool:
        return self.cleanup_for_patient(self.patient_service, patient_id, self.output_dir)

    @staticmethod
    def cleanup_for_patient(patient_service: PatientService, patient_id: int,
                            output_dir: Path | str | None = None) -> bool:
        """Elimina el PNG por ID incluso si el registro ya está archivado o borrado."""
        with patient_service.repository.database.connect() as connection:
            row = connection.execute("SELECT uuid FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if row is None:
            return False
        directory = Path(output_dir).expanduser().resolve() if output_dir else qr_directory()
        target = directory / f"{row['uuid']}.png"
        existed = target.exists()
        target.unlink(missing_ok=True)
        return existed

    def remove_all(self) -> int:
        """Elimina QR generados previamente, sin tocar otros archivos del directorio."""
        return self.cleanup_all(self.output_dir)

    @staticmethod
    def cleanup_all(output_dir: Path | str | None = None) -> int:
        directory = Path(output_dir).expanduser().resolve() if output_dir else qr_directory()
        if not directory.exists():
            return 0
        removed = 0
        for path in directory.iterdir():
            if path.suffix == ".png" and UUID_V4_PATTERN.fullmatch(path.stem) and (path.is_file() or path.is_symlink()):
                path.unlink(missing_ok=True)
                removed += 1
        return removed
