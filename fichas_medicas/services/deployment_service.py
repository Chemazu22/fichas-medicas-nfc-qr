"""Publicación controlada de perfiles consentidos mediante Git."""

from __future__ import annotations

import re
import shutil
import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.profile_service import ProfileService
from fichas_medicas.services.publication_state import PublicationStateStore

_UUID_HTML = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.html$")
_REMOTE_SCP = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+(?:\.git)?$")


class DeploymentError(RuntimeError):
    """Error de configuración o ejecución del despliegue."""


@dataclass(frozen=True, slots=True)
class DeploymentResult:
    status: str
    message: str
    commit: str | None = None
    files: tuple[str, ...] = ()


class DeploymentService:
    """Sincroniza únicamente UUID.html y styles.css desde la salida consentida."""

    def __init__(
        self,
        repository_dir: Path | str,
        profile_service: ProfileService,
        *,
        remote_name: str = "origin",
        timeout_seconds: int = 60,
        publication_state: PublicationStateStore | None = None,
    ) -> None:
        self.repository_dir = Path(repository_dir).expanduser().resolve()
        self.profile_service = profile_service
        self.patient_service = profile_service.patient_service
        self.source_dir = profile_service.output_dir.resolve()
        self.remote_name = remote_name
        self.publication_state = publication_state or PublicationStateStore()
        self.remote_url: str | None = None
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", remote_name):
            raise ValidationError("Nombre de remoto Git no válido.")
        if not 5 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds debe estar entre 5 y 600.")
        self.timeout_seconds = timeout_seconds
        if (
            self.repository_dir == self.source_dir
            or self.repository_dir in self.source_dir.parents
            or self.source_dir in self.repository_dir.parents
        ):
            raise ValidationError("La carpeta de perfiles debe estar fuera del repositorio Git.")

    @staticmethod
    def validate_remote_url(value: str) -> str:
        """Acepta URLs HTTPS sin credenciales o la sintaxis SSH usuario@host:path."""
        if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValidationError("URL de repositorio inválida.")
        if _REMOTE_SCP.fullmatch(value):
            return value
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError as exc:
            raise ValidationError("URL de repositorio inválida.") from exc
        if (
            parsed.scheme.lower() not in {"https", "ssh"}
            or not parsed.hostname
            or parsed.username not in (None, "git")
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.strip("/")
        ):
            raise ValidationError("Usa HTTPS sin credenciales o SSH configurado en el sistema.")
        return value

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args,
                cwd=self.repository_dir,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError as exc:
            raise DeploymentError("No se encontró Git. Instálalo desde Xcode Command Line Tools o git-scm.") from exc
        except subprocess.TimeoutExpired as exc:
            raise DeploymentError(f"Git superó el tiempo límite de {self.timeout_seconds} segundos.") from exc
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Git terminó con error."
            if self.remote_url:
                message = message.replace(self.remote_url, "[remoto configurado]")
            raise DeploymentError(message[-2000:])
        return result

    def verify(self) -> dict[str, str | bool | None]:
        if not self.repository_dir.is_dir():
            raise DeploymentError("La carpeta configurada para el repositorio no existe.")
        try:
            version = subprocess.run(
                ["git", "--version"], text=True, capture_output=True, timeout=10, check=False, shell=False
            )
        except FileNotFoundError as exc:
            raise DeploymentError("No se encontró Git. Instálalo desde Xcode Command Line Tools o git-scm.") from exc
        if version.returncode != 0:
            raise DeploymentError("Git no está instalado o no se puede ejecutar.")
        root = self._run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(root).resolve() != self.repository_dir:
            raise DeploymentError("repository_dir debe apuntar a la raíz del repositorio Git.")
        branch_result = self._run(["git", "branch", "--show-current"])
        branch = branch_result.stdout.strip()
        if not branch:
            raise DeploymentError("El repositorio está en detached HEAD; selecciona una rama antes de publicar.")
        remote_result = self._run(["git", "remote", "get-url", self.remote_name], check=False)
        remote = remote_result.stdout.strip() if remote_result.returncode == 0 else None
        if remote:
            try:
                self.validate_remote_url(remote)
            except ValidationError as exc:
                raise DeploymentError(
                    f"El remoto {self.remote_name} contiene una URL no admitida o credenciales embebidas."
                ) from exc
            self.remote_url = remote
            push_result = self._run(["git", "remote", "get-url", "--push", self.remote_name], check=False)
            push_url = push_result.stdout.strip() if push_result.returncode == 0 else remote
            try:
                self.validate_remote_url(push_url)
            except ValidationError as exc:
                raise DeploymentError(
                    f"El push URL del remoto {self.remote_name} contiene una URL no admitida o credenciales embebidas."
                ) from exc
        return {"git_version": version.stdout.strip(), "branch": branch, "remote": remote, "ready": bool(remote)}

    def configure_remote(self, remote_url: str) -> str:
        safe_url = self.validate_remote_url(remote_url)
        root = self._run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
        if Path(root).resolve() != self.repository_dir:
            raise DeploymentError("repository_dir debe apuntar a la raíz del repositorio Git.")
        if not self._run(["git", "branch", "--show-current"]).stdout.strip():
            raise DeploymentError("El repositorio está en detached HEAD; selecciona una rama primero.")
        remotes = self._run(["git", "remote"], check=True).stdout.splitlines()
        if self.remote_name in remotes:
            self._run(["git", "remote", "set-url", self.remote_name, safe_url])
        else:
            self._run(["git", "remote", "add", self.remote_name, safe_url])
        self.remote_url = safe_url
        return safe_url

    def _sync_authorized_profiles(self) -> tuple[str, ...]:
        self.repository_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        repository = self.patient_service.repository
        offset = 0
        page_size = 500
        authorized_files: set[str] = set()
        while True:
            patients = repository.list_all(include_deleted=True, offset=offset, limit=page_size)
            for patient in patients:
                if patient.status == "active" and self.patient_service.public_profile_data(patient.id) is not None:
                    generated = self.profile_service.generate(patient.id)
                    if generated is not None:
                        authorized_files.add(generated.name)
                else:
                    self.profile_service.remove(patient.id)
            if len(patients) < page_size:
                break
            offset += page_size

        expected: set[str] = set()
        for source in self.source_dir.iterdir():
            if not _UUID_HTML.fullmatch(source.name) or source.name not in authorized_files:
                if _UUID_HTML.fullmatch(source.name) and source.name not in authorized_files:
                    source.unlink(missing_ok=True)
                continue
            if source.is_symlink() or not source.is_file():
                raise DeploymentError(f"El perfil {source.name} no es un archivo regular.")
            target = self.repository_dir / source.name
            if target.is_symlink():
                raise DeploymentError(f"El destino {source.name} es un enlace simbólico.")
            shutil.copyfile(source, target)
            expected.add(source.name)

        for existing in self.repository_dir.iterdir():
            if _UUID_HTML.fullmatch(existing.name) and existing.name not in expected:
                if existing.is_symlink():
                    raise DeploymentError(f"El destino {existing.name} es un enlace simbólico.")
                if existing.is_file():
                    existing.unlink()

        stylesheet = self.source_dir / "styles.css"
        target_stylesheet = self.repository_dir / "styles.css"
        if expected:
            if stylesheet.is_symlink() or not stylesheet.is_file():
                raise DeploymentError("No se encontró la hoja de estilos de los perfiles generados.")
            if target_stylesheet.is_symlink():
                raise DeploymentError("El destino styles.css es un enlace simbólico.")
            shutil.copyfile(stylesheet, target_stylesheet)
            expected.add("styles.css")
        elif target_stylesheet.exists():
            if target_stylesheet.is_symlink():
                raise DeploymentError("El destino styles.css es un enlace simbólico.")
            if target_stylesheet.is_file():
                target_stylesheet.unlink()
                expected.add("styles.css")
        return tuple(sorted(expected))

    def publish(self, commit_message: str = "Publicar perfiles médicos autorizados") -> DeploymentResult:
        state = self.verify()
        if not state["remote"]:
            raise DeploymentError("Configura primero el remoto Git del repositorio.")
        staged = self._run(["git", "diff", "--cached", "--quiet"], check=False)
        if staged.returncode == 1:
            raise DeploymentError("Hay cambios ya preparados en Git. Confírmalos o retíralos antes de publicar.")
        if staged.returncode != 0:
            raise DeploymentError("No se pudo revisar el estado preparado de Git.")

        paths = self._sync_authorized_profiles()
        tracked = set(self._run(["git", "ls-files", "--", "*.html", "styles.css"]).stdout.splitlines())
        managed = sorted(set(paths) | {name for name in tracked if _UUID_HTML.fullmatch(name) or name == "styles.css"})
        if managed:
            self._run(["git", "add", "-f", "-A", "--", *managed])
        diff = self._run(["git", "diff", "--cached", "--quiet"], check=False)
        commit = None
        changed: tuple[str, ...] = ()
        if diff.returncode == 1:
            changed = tuple(
                line for line in self._run(["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
            )
            message = commit_message.strip() if isinstance(commit_message, str) else ""
            if not message or len(message) > 200:
                raise DeploymentError("El mensaje de commit debe tener entre 1 y 200 caracteres.")
            self._run(["git", "commit", "-m", message])
            commit = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        elif diff.returncode != 0:
            raise DeploymentError("No se pudo revisar el diff preparado.")
        if commit is None:
            return DeploymentResult(
                status="no_changes", message="No hay cambios nuevos que publicar.", commit=self._head()
            )
        try:
            self._push()
        except DeploymentError as exc:
            return DeploymentResult(
                status="push_failed",
                message=f"Los archivos quedaron guardados localmente. Puedes reintentar el push. {exc}",
                commit=commit or self._head(),
                files=changed,
            )
        state_warning = self._record_publication_state()
        message = "Perfiles publicados correctamente."
        if state_warning:
            message += f" No se pudo actualizar el indicador local de publicación: {state_warning}"
        return DeploymentResult(status="published", message=message, commit=commit, files=changed)

    def retry_push(self) -> DeploymentResult:
        state = self.verify()
        if not state["remote"]:
            raise DeploymentError("Configura primero el remoto Git del repositorio.")
        self._push()
        warning = self._record_publication_state()
        message = "Cambios locales enviados correctamente."
        if warning:
            message += f" No se pudo actualizar el indicador local de publicación: {warning}"
        return DeploymentResult(status="pushed", message=message, commit=self._head())

    def _record_publication_state(self) -> str | None:
        """Compara el HEAD ya enviado con las proyecciones autorizadas actuales."""
        previous = self.publication_state.all()
        states: dict[str, str] = {}
        repository = self.patient_service.repository
        current_ids: set[str] = set()
        offset = 0
        while True:
            patients = repository.list_all(include_deleted=True, offset=offset, limit=500)
            for patient in patients:
                current_ids.add(patient.uuid)
                target = self.repository_dir / f"{patient.uuid}.html"
                authorized = patient.status == "active" and self.patient_service.public_profile_data(patient.id) is not None
                if authorized:
                    generated = self.profile_service.generate(patient.id)
                    matches = bool(generated and not target.is_symlink() and target.is_file()
                                   and target.read_bytes() == generated.read_bytes())
                    if matches:
                        states[patient.uuid] = "published"
                    else:
                        states[patient.uuid] = "pending_update" if previous.get(patient.uuid) == "published" else "pending_publish"
                elif target.exists():
                    states[patient.uuid] = "pending_removal"
                elif patient.uuid in previous:
                    states[patient.uuid] = "removed"
            if len(patients) < 500:
                break
            offset += 500
        for name in self.repository_dir.iterdir():
            if _UUID_HTML.fullmatch(name.name):
                patient_uuid = name.name[:-5]
                if patient_uuid not in current_ids and name.exists():
                    states[patient_uuid] = "pending_removal"
        try:
            self.publication_state.replace(states)
            return None
        except Exception as exc:
            return str(exc)

    def _push(self) -> None:
        state = self.verify()
        branch = str(state["branch"])
        self._run(["git", "push", self.remote_name, branch])

    def _head(self) -> str | None:
        result = self._run(["git", "rev-parse", "HEAD"], check=False)
        return result.stdout.strip() if result.returncode == 0 else None
