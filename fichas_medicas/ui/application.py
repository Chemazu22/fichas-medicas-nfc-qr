"""Ventana principal y navegación de la aplicación."""

from __future__ import annotations

import queue
import logging
import threading
import webbrowser
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from fichas_medicas.config.app_settings import AppSettings
from fichas_medicas.database.repository import PatientRepository
from fichas_medicas.security.validation import ValidationError
from fichas_medicas.services.deployment_service import DeploymentError, DeploymentService
from fichas_medicas.services.backup_service import BackupInfo, BackupService
from fichas_medicas.services.patient_service import PatientService
from fichas_medicas.services.profile_service import ProfileService
from fichas_medicas.services.publication_state import PublicationStateStore
from fichas_medicas.services.qr_service import QrService
from fichas_medicas.ui.registration import ConsentDialog, PatientFormDialog

logger = logging.getLogger(__name__)


class MedicalRecordsApp(ctk.CTk):
    NAVIGATION = ["Dashboard", "Registrar persona", "Expedientes médicos", "Perfiles digitales",
                  "Códigos QR", "Publicaciones", "Respaldos", "Configuración", "Acerca del sistema"]

    def __init__(self, repository: PatientRepository, patients: PatientService, profiles: ProfileService,
                 settings: AppSettings):
        super().__init__()
        self.repository, self.patients, self.profiles, self.settings = repository, patients, profiles, settings
        self.backups = BackupService(repository.database)
        self.publication_state = PublicationStateStore()
        self.title("Fichas Médicas")
        self.geometry("1180x790")
        self.minsize(920, 640)
        ctk.set_appearance_mode(settings.values.get("appearance", "System"))
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=26, pady=24)
        self.content.grid_columnconfigure(0, weight=1)
        self.job_queue: queue.Queue = queue.Queue()
        self.job_running = False
        self._render("Dashboard")
        self.after(150, self._poll_jobs)

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text="✚  Fichas Médicas", font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="w", padx=18, pady=(25, 4)
        )
        ctk.CTkLabel(sidebar, text="GESTIÓN SEGURA DE EXPEDIENTES", font=ctk.CTkFont(size=9, weight="bold"),
                     text_color="gray").pack(anchor="w", padx=18, pady=(0, 20))
        for item in self.NAVIGATION:
            ctk.CTkButton(sidebar, text=item, anchor="w", height=40, corner_radius=9,
                          fg_color="transparent", text_color=("#263b42", "#d6e1e2"),
                          hover_color=("#e5f1f0", "#263b42"), command=lambda name=item: self._render(name)).pack(
                              fill="x", padx=12, pady=3
                          )
        ctk.CTkLabel(sidebar, text="Datos locales protegidos por tu cuenta de macOS",
                     text_color="gray", wraplength=175, justify="left").pack(side="bottom", padx=18, pady=18)

    def _clear(self):
        for child in self.content.winfo_children():
            child.destroy()

    def _header(self, title, subtitle=""):
        ctk.CTkLabel(self.content, text=title, font=ctk.CTkFont(size=28, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        if subtitle:
            ctk.CTkLabel(self.content, text=subtitle, text_color="gray", wraplength=800, justify="left").grid(
                row=1, column=0, sticky="w", pady=(4, 18)
            )

    def _render(self, section):
        if getattr(self, "job_running", False):
            messagebox.showinfo("Operación en curso", "Espera a que termine antes de cambiar de sección.", parent=self)
            return
        self.current_section = section
        self._clear()
        if section == "Dashboard": self._dashboard()
        elif section == "Registrar persona": self._registration_page()
        elif section == "Expedientes médicos": self._records_page()
        elif section == "Perfiles digitales": self._profiles_page()
        elif section == "Códigos QR": self._qr_page()
        elif section == "Publicaciones": self._publication_page()
        elif section == "Respaldos": self._backups_page()
        elif section == "Configuración": self._settings_page()
        else: self._about_page()

    def _dashboard(self):
        self._header("Dashboard", "Resumen de expedientes y actividad local.")
        records = self._all_patients()
        active = [p for p in records if p.status == "active"]
        authorized = [p for p in active if self.patients.public_profile_data(p.id) is not None]
        cards = ctk.CTkFrame(self.content, fg_color="transparent")
        cards.grid(row=2, column=0, sticky="ew")
        archived_count = sum(p.status == "archived" for p in records)
        for i, (label, value) in enumerate([("PERSONAS ACTIVAS", len(active)), ("PERFILES AUTORIZADOS", len(authorized)),
                                            ("EXPEDIENTES ARCHIVADOS", archived_count)]):
            cards.grid_columnconfigure(i, weight=1)
            card = ctk.CTkFrame(cards, corner_radius=14)
            card.grid(row=0, column=i, padx=(0, 12), sticky="ew")
            ctk.CTkLabel(card, text=label, text_color="gray", font=ctk.CTkFont(size=11, weight="bold")).pack(
                anchor="w", padx=18, pady=(16, 4)
            )
            ctk.CTkLabel(card, text=str(value), font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w", padx=18, pady=(0, 16))
        ctk.CTkLabel(self.content, text="Expedientes recientes", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=3, column=0, sticky="w", pady=(28, 12)
        )
        for i, patient in enumerate(sorted(active, key=lambda p: p.updated_at, reverse=True)[:6]):
            self._patient_row(self.content, patient, row=4 + i)
        ctk.CTkButton(self.content, text="＋  Registrar persona", command=lambda: self._render("Registrar persona")).grid(
            row=10, column=0, sticky="w", pady=20
        )

    def _registration_page(self):
        self._header("Registrar persona", "Los datos se guardan localmente. El perfil público requiere consentimiento separado.")
        ctk.CTkButton(self.content, text="＋  Abrir formulario de registro", height=46,
                      command=lambda: PatientFormDialog(self, self.patients, lambda: self._render("Dashboard"))).grid(
                          row=2, column=0, sticky="w", pady=12
                      )

    def _records_page(self):
        self._header("Expedientes médicos", "Busca por nombre y administra datos, estado y autorización.")
        top = ctk.CTkFrame(self.content, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        search = ctk.CTkEntry(top, placeholder_text="Buscar por nombre…", width=360)
        search.pack(side="left", padx=(0, 10))
        archived = ctk.CTkCheckBox(top, text="Incluir archivados")
        archived.pack(side="left")
        listing = ctk.CTkScrollableFrame(self.content)
        listing.grid(row=3, column=0, sticky="nsew")
        self.content.grid_rowconfigure(3, weight=1)
        def refresh(*_):
            for child in listing.winfo_children(): child.destroy()
            for i, patient in enumerate(self.patients.search(search.get(), include_archived=bool(archived.get()), limit=500)):
                self._patient_row(listing, patient, i)
        ctk.CTkButton(top, text="Buscar", command=refresh).pack(side="left")
        search.bind("<Return>", refresh)
        archived.configure(command=refresh)
        refresh()

    def _patient_row(self, parent, patient, row):
        card = ctk.CTkFrame(parent, corner_radius=11)
        card.grid(row=row, column=0, sticky="ew", pady=5)
        card.grid_columnconfigure(0, weight=1)
        consented = self.patients.public_profile_data(patient.id) is not None
        status_text = f"{patient.status}  ·  {'Autorizado para publicar' if consented else 'Privado'}"
        publication = self.publication_state.get(patient.uuid)
        publication_labels = {
            "published": "Último push confirmado",
            "pending_publish": "Pendiente de publicar",
            "pending_update": "Pendiente de actualizar en Pages",
            "pending_removal": "Revocación pendiente de publicar",
            "removed": "Publicación retirada",
        }
        if publication:
            status_text += f"  ·  {publication_labels[publication]}"
        elif consented:
            status_text += "  ·  Pendiente de publicar"
        ctk.CTkLabel(card, text=patient.full_name, font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 0)
        )
        ctk.CTkLabel(card, text=status_text, text_color="gray").grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 10))
        ctk.CTkButton(card, text="Editar", width=72, command=lambda p=patient: PatientFormDialog(
            self, self.patients, lambda: self._patient_changed(p.id), p)).grid(row=0, column=1, rowspan=2, padx=5)
        ctk.CTkButton(card, text="Consentimiento", width=120, command=lambda p=patient: ConsentDialog(
            self, self.patients, p, lambda: self._patient_changed(p.id))).grid(row=0, column=2, rowspan=2, padx=(5, 12))
        ctk.CTkButton(card, text="Eliminar", width=76, fg_color="#9b3f28",
                      command=lambda p=patient: self._delete_patient(p)).grid(row=0, column=3, rowspan=2, padx=(0, 12))
        ctk.CTkButton(card, text="Reactivar" if patient.status == "archived" else "Archivar", width=84,
                      fg_color="transparent", border_width=1,
                      command=lambda p=patient: self._toggle_archive(p)).grid(row=0, column=4, rowspan=2, padx=(0, 12))

    def _toggle_archive(self, patient):
        try:
            status = "active" if patient.status == "archived" else "archived"
            self.repository.set_status(patient.id, status)
            if status != "active":
                self._remove_local_artifacts(patient.id)
            self._update_publication_state(patient.uuid)
            self._render("Expedientes médicos")
        except Exception as exc:
            messagebox.showerror("No se pudo cambiar el estado", str(exc), parent=self)

    def _delete_patient(self, patient):
        if messagebox.askyesno("Eliminar expediente", f"¿Marcar como eliminado el expediente de {patient.full_name}?", parent=self):
            try:
                self.patients.delete(patient.id)
                self._remove_local_artifacts(patient.id)
                self._update_publication_state(patient.uuid)
                self._render("Expedientes médicos")
            except Exception as exc:
                messagebox.showerror("No se pudo eliminar", str(exc), parent=self)

    def _patient_changed(self, patient_id):
        # Cualquier cambio de datos o autorización invalida renders locales previos.
        patient = self.repository.get(patient_id)
        if patient:
            self._update_publication_state(patient.uuid)
        self._remove_local_artifacts(patient_id)
        self._render("Expedientes médicos")

    def _update_publication_state(self, patient_uuid):
        try:
            previous = self.publication_state.get(patient_uuid)
            patient = self.repository.get_by_uuid(patient_uuid)
            authorized = bool(patient and self.patients.public_profile_data(patient.id) is not None)
            if authorized:
                state = "pending_update" if previous == "published" else "pending_publish"
                self.publication_state.set(patient_uuid, state)
            elif previous == "pending_publish":
                self.publication_state.remove(patient_uuid)
            elif previous in {"published", "pending_update", "pending_removal"}:
                self.publication_state.set(patient_uuid, "pending_removal")
        except Exception as exc:
            logger.exception("No se pudo actualizar el estado local de publicación")
            messagebox.showwarning(
                "Estado de publicación", f"El cambio se guardó, pero el indicador local no pudo actualizarse: {exc}", parent=self
            )

    def _all_patients(self):
        result, offset = [], 0
        while True:
            batch = self.repository.list_all(offset=offset, limit=500)
            result.extend(batch)
            if len(batch) < 500:
                return result
            offset += 500

    def _profiles_page(self):
        self._header("Perfiles digitales", "Genera HTML solo para expedientes activos con autorización vigente.")
        listing = ctk.CTkScrollableFrame(self.content)
        listing.grid(row=2, column=0, sticky="nsew")
        self.content.grid_rowconfigure(2, weight=1)
        active = [p for p in self._all_patients() if p.status == "active"]
        for i, patient in enumerate(active):
            card = ctk.CTkFrame(listing); card.grid(row=i, column=0, sticky="ew", pady=5)
            ctk.CTkLabel(card, text=patient.full_name).pack(side="left", padx=12, pady=10)
            ctk.CTkButton(card, text="Generar / actualizar", command=lambda p=patient: self._generate_profile(p.id)).pack(side="right", padx=10)

    def _generate_profile(self, patient_id):
        try:
            path = self.profiles.generate(patient_id)
            messagebox.showinfo("Perfil", f"Perfil generado: {path}" if path else "No hay consentimiento vigente.", parent=self)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _remove_local_artifacts(self, patient_id):
        """Invalida HTML y QR local al editar, revocar, archivar o eliminar."""
        self.profiles.remove(patient_id)
        QrService.cleanup_for_patient(self.patients, patient_id)

    def _qr_page(self):
        self._header("Códigos QR y NFC", "El QR contiene una URL pública. NFC se programa con un dispositivo compatible.")
        base = self.settings.values.get("public_base_url", "")
        if not base:
            ctk.CTkLabel(self.content, text="Configura primero la URL pública en Configuración.", text_color="#9b3f28").grid(row=2, column=0, sticky="w")
        listing = ctk.CTkScrollableFrame(self.content); listing.grid(row=3, column=0, sticky="nsew", pady=12)
        self.content.grid_rowconfigure(3, weight=1)
        for i, patient in enumerate([p for p in self._all_patients() if p.status == "active"]):
            card = ctk.CTkFrame(listing); card.grid(row=i, column=0, sticky="ew", pady=5)
            ctk.CTkLabel(card, text=patient.full_name).pack(side="left", padx=12, pady=10)
            ctk.CTkButton(card, text="Generar QR", command=lambda p=patient: self._make_qr(p.id)).pack(side="right", padx=8)
            ctk.CTkButton(card, text="Copiar URL", fg_color="transparent", border_width=1,
                          command=lambda p=patient: self._copy_profile_url(p.id)).pack(side="right", padx=8)
            ctk.CTkButton(card, text="Abrir URL", fg_color="transparent", border_width=1,
                          command=lambda p=patient: self._open_profile_url(p.id)).pack(side="right", padx=8)

    def _make_qr(self, patient_id):
        try:
            qr = QrService(self.patients, self.settings.values.get("public_base_url"))
            path = qr.generate_for_patient(patient_id)
            if path:
                self._show_qr_preview(path, qr.nfc_payload(patient_id))
            else: messagebox.showwarning("Código QR", "El perfil no tiene consentimiento vigente.", parent=self)
        except Exception as exc:
            messagebox.showerror("No se pudo generar el QR", str(exc), parent=self)

    def _copy_profile_url(self, patient_id):
        try:
            url = QrService(self.patients, self.settings.values.get("public_base_url")).nfc_payload(patient_id)
            self.clipboard_clear(); self.clipboard_append(url)
            messagebox.showinfo("URL copiada", "La URL autorizada quedó en el portapapeles.", parent=self)
        except Exception as exc: messagebox.showerror("URL no disponible", str(exc), parent=self)

    def _open_profile_url(self, patient_id):
        try:
            url = QrService(self.patients, self.settings.values.get("public_base_url")).nfc_payload(patient_id)
            webbrowser.open(url)
        except Exception as exc: messagebox.showerror("URL no disponible", str(exc), parent=self)

    def _show_qr_preview(self, path, url):
        from PIL import Image
        window = ctk.CTkToplevel(self); window.title("Código QR"); window.geometry("420x540"); window.transient(self)
        image = ctk.CTkImage(light_image=Image.open(path), dark_image=Image.open(path), size=(300, 300))
        ctk.CTkLabel(window, text="Escanea para abrir el perfil autorizado", wraplength=360).pack(pady=(18, 8))
        ctk.CTkLabel(window, text="", image=image).pack(padx=20, pady=8)
        ctk.CTkLabel(window, text=url, wraplength=360, text_color="gray").pack(padx=20, pady=8)
        buttons = ctk.CTkFrame(window, fg_color="transparent"); buttons.pack(pady=12)
        ctk.CTkButton(buttons, text="Copiar URL", command=lambda: (self.clipboard_clear(), self.clipboard_append(url))).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Abrir URL", command=lambda: webbrowser.open(url)).pack(side="left", padx=6)
        ctk.CTkLabel(window, text=f"PNG: {path}", wraplength=360, text_color="gray").pack(pady=4)

    def _publication_page(self):
        self._header("Publicaciones", "Git se ejecutará en segundo plano. La autenticación debe estar configurada en macOS.")
        ctk.CTkLabel(self.content, text="Los cambios y revocaciones quedan pendientes hasta completar un push exitoso.",
                     text_color="#9b3f28", wraplength=760, justify="left").grid(row=2, column=0, sticky="w", pady=(0, 8))
        state = ctk.CTkLabel(self.content, text="Revisa Configuración para conectar el repositorio.", wraplength=700)
        state.grid(row=3, column=0, sticky="w", pady=8)
        ctk.CTkButton(self.content, text="Verificar Git y remoto", command=lambda: self._verify_deployment(state)).grid(row=4, column=0, sticky="w", pady=6)
        ctk.CTkButton(self.content, text="Publicar perfiles autorizados", command=lambda: self._run_deployment(state)).grid(row=5, column=0, sticky="w", pady=6)
        self.progress = ctk.CTkProgressBar(self.content, mode="indeterminate"); self.progress.grid(row=6, column=0, sticky="ew", pady=16); self.progress.set(0)
        ctk.CTkButton(self.content, text="Reintentar push pendiente", command=lambda: self._retry_deployment(state)).grid(row=7, column=0, sticky="w")

    def _deployment(self):
        repo_path = self.settings.values.get("repository_dir", "")
        if not repo_path: raise DeploymentError("Selecciona la carpeta checkout en Configuración.")
        service = DeploymentService(Path(repo_path), self.profiles)
        remote = self.settings.values.get("remote_url", "")
        if remote: service.configure_remote(remote)
        return service

    def _verify_deployment(self, label):
        self._start_job(label, lambda: self._deployment().verify())

    def _run_deployment(self, label):
        self._start_job(label, lambda: self._deployment().publish())

    def _retry_deployment(self, label):
        self._start_job(label, lambda: self._deployment().retry_push())

    def _start_job(self, label, action):
        if self.job_running:
            messagebox.showinfo("Operación en curso", "Espera a que termine la operación actual.", parent=self)
            return
        self.job_running = True
        progress = getattr(self, "progress", None)
        if self._widget_exists(progress): progress.start()
        if self._widget_exists(label): label.configure(text="Operación en curso…")
        def worker():
            try: result = action()
            except Exception as exc: result = exc
            self.job_queue.put((label, progress, result))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_jobs(self):
        try:
            label, progress, result = self.job_queue.get_nowait()
            self.job_running = False
            try:
                if progress and progress.winfo_exists(): progress.stop(); progress.set(0)
                if label.winfo_exists():
                    if isinstance(result, Exception):
                        label.configure(text=f"Error: {result}")
                        messagebox.showerror("Operación fallida", str(result), parent=self)
                    elif hasattr(result, "message"):
                        label.configure(text=result.message)
                        messagebox.showinfo("Publicación", result.message, parent=self)
                    elif isinstance(result, tuple) and len(result) == 2 and hasattr(result[0], "restored_from"):
                        restore_result, warning = result
                        safety = f"\nCopia anterior: {restore_result.safety_backup}" if restore_result.safety_backup else ""
                        warning_text = f"\nAviso de limpieza local: {warning}" if warning else ""
                        summary = f"Base restaurada desde {restore_result.restored_from}.\nArchivo activo: {restore_result.database_path}.{safety}{warning_text}"
                        label.configure(text="Restauración completada.")
                        messagebox.showinfo("Restauración completada", summary, parent=self)
                    elif isinstance(result, list) and all(isinstance(item, BackupInfo) for item in result):
                        label.configure(text=f"{len(result)} respaldo(s) revisado(s).")
                        if getattr(self, "current_section", None) == "Respaldos":
                            self._render_backup_items(result)
                    elif isinstance(result, dict) and "git_version" in result:
                        label.configure(text=f"Git: {result['git_version']}  ·  Rama: {result['branch']}  ·  Remoto: {'configurado' if result['remote'] else 'falta configurar'}")
                    else:
                        label.configure(text=str(result))
                        messagebox.showinfo("Operación completada", str(result), parent=self)
                    if (isinstance(result, Path) or isinstance(result, tuple) and result and hasattr(result[0], "restored_from")) and getattr(
                        self, "current_section", None) == "Respaldos":
                        self._refresh_backups()
            except Exception:
                pass
        except queue.Empty: pass
        self.after(150, self._poll_jobs)

    @staticmethod
    def _widget_exists(widget):
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _backups_page(self):
        self._header("Respaldos", "Copias consistentes de SQLite guardadas en Application Support, fuera del repositorio Pages.")
        ctk.CTkButton(self.content, text="Crear respaldo", command=self._create_backup).grid(
            row=2, column=0, sticky="w", pady=(0, 12))
        self.backup_list = ctk.CTkScrollableFrame(self.content, height=300)
        self.backup_list.grid(row=3, column=0, sticky="nsew")
        self.content.grid_rowconfigure(3, weight=1)
        self.backup_status = ctk.CTkLabel(self.content, text="", text_color="gray", wraplength=800)
        self.backup_status.grid(row=4, column=0, sticky="w", pady=8)
        self._refresh_backups()

    def _refresh_backups(self):
        self.backup_status.configure(text="Revisando respaldos e integridad…")
        self._start_job(self.backup_status, self.backups.list_backups)

    def _render_backup_items(self, backups):
        for child in self.backup_list.winfo_children():
            child.destroy()
        if not backups:
            ctk.CTkLabel(self.backup_list, text="No hay respaldos disponibles.").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        for index, backup in enumerate(backups):
            row = ctk.CTkFrame(self.backup_list)
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)
            size = f"{backup.size_bytes / 1024:.1f} KB"
            ctk.CTkLabel(row, text=f"{backup.path.name} · {size} · integridad: {backup.integrity}",
                         anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=9)
            ctk.CTkButton(row, text="Restaurar…", width=100,
                          command=lambda path=backup.path: self._restore_backup(path)).grid(row=0, column=1, padx=8)

    def _create_backup(self):
        self._start_job(self.backup_status, self.backups.create_backup)

    def _restore_backup(self, path):
        if not messagebox.askyesno(
            "Confirmar restauración",
            "La base de datos actual se reemplazará. Antes se creará un respaldo de seguridad. ¿Continuar?",
            parent=self,
        ):
            return
        self._start_job(self.backup_status, lambda: self._restore_backup_and_sync(path))

    def _restore_backup_and_sync(self, path):
        result = self.backups.restore(path, confirm_overwrite=True)
        warning = self._after_database_restore()
        return result, warning

    def _after_database_restore(self):
        """Invalida renders de la base anterior y marca el estado Pages como pendiente."""
        warning = None
        try:
            self.profiles.remove_all()
            QrService.cleanup_all()
        except Exception as exc:
            warning = str(exc)
        previous = self.publication_state.all()
        states = {}
        current_ids = set()
        offset = 0
        while True:
            patients = self.repository.list_all(include_deleted=True, offset=offset, limit=500)
            for patient in patients:
                current_ids.add(patient.uuid)
                old = previous.get(patient.uuid)
                authorized = patient.status == "active" and self.patients.public_profile_data(patient.id) is not None
                if authorized:
                    states[patient.uuid] = "pending_update" if old in {"published", "pending_update"} else "pending_publish"
                elif old in {"published", "pending_update", "pending_removal"}:
                    states[patient.uuid] = "pending_removal"
                elif old == "removed":
                    states[patient.uuid] = "removed"
            if len(patients) < 500:
                break
            offset += 500
        for patient_uuid, old in previous.items():
            if patient_uuid not in current_ids and old in {"published", "pending_update", "pending_removal"}:
                states[patient_uuid] = "pending_removal"
            elif patient_uuid not in current_ids and old == "removed":
                states[patient_uuid] = "removed"
        try:
            self.publication_state.replace(states)
        except Exception as exc:
            warning = f"no se pudo actualizar el estado de publicación: {exc}"
        return warning

    def _settings_page(self):
        self._header("Configuración", "Las rutas se guardan localmente. No guardes tokens o contraseñas aquí.")
        values = self.settings.values
        self.url_entry = self._setting_field(2, "URL pública base de GitHub Pages", values.get("public_base_url", ""))
        self.repo_entry = self._setting_field(4, "Carpeta del repositorio Pages", values.get("repository_dir", ""))
        ctk.CTkButton(self.content, text="Seleccionar carpeta…", command=self._choose_repo).grid(row=5, column=0, sticky="w", pady=4)
        self.remote_entry = self._setting_field(6, "URL Git remota (HTTPS sin token o SSH)", values.get("remote_url", ""))
        self.appearance = ctk.CTkComboBox(self.content, values=["System", "Light", "Dark"])
        self.appearance.set(values.get("appearance", "System"))
        ctk.CTkLabel(self.content, text="Apariencia").grid(row=8, column=0, sticky="w", pady=(12, 3))
        self.appearance.grid(row=9, column=0, sticky="ew")
        ctk.CTkButton(self.content, text="Guardar configuración", command=self._save_settings).grid(row=10, column=0, sticky="w", pady=20)
        self.settings_status = ctk.CTkLabel(self.content, text="", text_color="gray"); self.settings_status.grid(row=11, column=0, sticky="w")

    def _setting_field(self, row, label, value):
        ctk.CTkLabel(self.content, text=label).grid(row=row, column=0, sticky="w", pady=(12, 3))
        entry = ctk.CTkEntry(self.content, width=700); entry.insert(0, value); entry.grid(row=row + 1, column=0, sticky="ew")
        return entry

    def _choose_repo(self):
        path = filedialog.askdirectory(parent=self, title="Selecciona el checkout de GitHub Pages")
        if path: self.repo_entry.delete(0, "end"); self.repo_entry.insert(0, path)

    def _save_settings(self):
        try:
            self.settings.save(public_base_url=self.url_entry.get().strip(), repository_dir=self.repo_entry.get().strip(),
                               remote_url=self.remote_entry.get().strip(), appearance=self.appearance.get())
            ctk.set_appearance_mode(self.appearance.get())
            self.settings_status.configure(text="Configuración guardada.")
        except Exception as exc: self.settings_status.configure(text=str(exc), text_color="#b42318")

    def _about_page(self):
        self._header("Acerca del sistema", "Gestión local de fichas médicas NFC/QR.")
        ctk.CTkLabel(self.content, text="Los perfiles alojados en GitHub Pages son públicos y no ofrecen control de acceso.\nLa información publicada debe contar con autorización explícita.\n\nVersión 0.1.0 · Datos locales SQLite", justify="left").grid(row=2, column=0, sticky="w")
