"""Diálogos para registrar, editar y autorizar expedientes."""

from __future__ import annotations

import calendar
import re
from datetime import date

import customtkinter as ctk

from fichas_medicas.database.models import Patient
from fichas_medicas.services.patient_service import PUBLIC_FIELDS, PatientService


class DatePickerDialog(ctk.CTkToplevel):
    """Selector de fecha sencillo, sin una dependencia de calendario externa."""

    MONTHS = (
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    )

    def __init__(self, master, current_value: str, on_select):
        super().__init__(master)
        self.title("Elegir fecha de nacimiento")
        self.geometry("340x365")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.on_select = on_select
        try:
            selected = date.fromisoformat(current_value) if current_value else date.today()
        except ValueError:
            selected = date.today()
        self.year, self.month = selected.year, selected.month

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkButton(header, text="‹", width=42, command=lambda: self._move_month(-1)).pack(side="left")
        self.month_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.month_label.pack(side="left", expand=True)
        ctk.CTkButton(header, text="›", width=42, command=lambda: self._move_month(1)).pack(side="right")
        self.days_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.days_frame.pack(fill="both", expand=True, padx=14, pady=4)
        ctk.CTkLabel(self, text="Selecciona un día; las fechas futuras no están disponibles.",
                     text_color="gray", wraplength=310).pack(pady=(4, 12))
        self._render_month()

    def _move_month(self, offset: int) -> None:
        self.month += offset
        if self.month < 1:
            self.month, self.year = 12, self.year - 1
        elif self.month > 12:
            self.month, self.year = 1, self.year + 1
        self._render_month()

    def _render_month(self) -> None:
        for child in self.days_frame.winfo_children():
            child.destroy()
        self.month_label.configure(text=f"{self.MONTHS[self.month - 1]} {self.year}")
        for column, weekday in enumerate(("L", "M", "M", "J", "V", "S", "D")):
            ctk.CTkLabel(self.days_frame, text=weekday, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=column, padx=2, pady=(2, 8), sticky="nsew"
            )
            self.days_frame.grid_columnconfigure(column, weight=1)
        for row, week in enumerate(calendar.monthcalendar(self.year, self.month), start=1):
            for column, day in enumerate(week):
                if day:
                    chosen = date(self.year, self.month, day)
                    ctk.CTkButton(
                        self.days_frame, text=str(day), width=35, height=34,
                        state="disabled" if chosen > date.today() else "normal",
                        command=lambda value=chosen: self._select(value),
                    ).grid(row=row, column=column, padx=2, pady=2, sticky="nsew")

    def _select(self, selected: date) -> None:
        self.on_select(selected.isoformat())
        self.destroy()


class PatientFormDialog(ctk.CTkToplevel):
    def __init__(self, master, service: PatientService, on_saved, patient: Patient | None = None):
        super().__init__(master)
        self.service, self.on_saved, self.patient = service, on_saved, patient
        self.title("Editar expediente" if patient else "Registrar persona")
        self.geometry("680x820")
        self.minsize(560, 640)
        self.transient(master)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=self.title(), font=ctk.CTkFont(size=23, weight="bold")).grid(
            row=0, column=0, padx=24, pady=(22, 4), sticky="w"
        )
        ctk.CTkLabel(self, text="Los campos no autorizados permanecerán en la base local.",
                     text_color="gray").grid(row=1, column=0, padx=24, sticky="w")
        self.form = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.form.grid(row=2, column=0, sticky="nsew", padx=18, pady=12)
        self.grid_rowconfigure(2, weight=1)
        self.entries = {}
        self.texts = {}
        row = 0
        fields = [
            ("full_name", "Nombre completo *", "entry"),
            ("date_of_birth", "Fecha de nacimiento", "date"),
            ("blood_type", "Tipo de sangre", "blood"),
            ("allergies", "Alergias", "text"),
            ("conditions", "Padecimientos", "text"),
            ("medications", "Medicamentos", "text"),
            ("additional_information", "Información adicional", "text"),
            (None, "Contactos de emergencia (hasta 3)", "section"),
            ("emergency_contact_name", "Contacto 1 · Nombre", "entry"),
            ("emergency_contact_relationship", "Contacto 1 · Parentesco", "entry"),
            ("emergency_contact_phone", "Contacto 1 · Teléfono", "phone"),
            ("emergency_contact_2_name", "Contacto 2 · Nombre", "entry"),
            ("emergency_contact_2_relationship", "Contacto 2 · Parentesco", "entry"),
            ("emergency_contact_2_phone", "Contacto 2 · Teléfono", "phone"),
            ("emergency_contact_3_name", "Contacto 3 · Nombre", "entry"),
            ("emergency_contact_3_relationship", "Contacto 3 · Parentesco", "entry"),
            ("emergency_contact_3_phone", "Contacto 3 · Teléfono", "phone"),
        ]
        for key, label, kind in fields:
            if kind == "section":
                ctk.CTkLabel(self.form, text=label, anchor="w", font=ctk.CTkFont(size=16, weight="bold")).grid(
                    row=row, column=0, sticky="ew", padx=8, pady=(18, 4)
                )
                row += 1
                continue
            ctk.CTkLabel(self.form, text=label, anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=row, column=0, sticky="ew", padx=8, pady=(9, 2)
            )
            value = getattr(patient, key, "") if patient else ""
            if kind == "text":
                widget = ctk.CTkTextbox(self.form, height=72, wrap="word")
                widget.insert("1.0", value or "")
                self.texts[key] = widget
            elif kind == "blood":
                widget = ctk.CTkComboBox(self.form, values=["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Desconocido"])
                widget.set(value or "")
                self.entries[key] = widget
            elif kind == "date":
                date_row = ctk.CTkFrame(self.form, fg_color="transparent")
                widget = ctk.CTkEntry(date_row, placeholder_text="AAAA-MM-DD")
                widget.insert(0, value or "")
                widget.pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    date_row, text="Calendario", width=112,
                    command=lambda entry=widget: DatePickerDialog(
                        self, entry.get(), lambda selected: self._set_entry(entry, selected)
                    ),
                ).pack(side="left", padx=(8, 0))
                widget = date_row
                self.entries[key] = date_row.winfo_children()[0]
            elif kind == "phone":
                validate = self.register(lambda value: bool(re.fullmatch(r"[0-9+().\s-]*", value)))
                widget = ctk.CTkEntry(
                    self.form,
                    placeholder_text="Solo números; puedes incluir +, espacios o guiones",
                    validate="key", validatecommand=(validate, "%P"),
                )
                widget.insert(0, value or "")
                self.entries[key] = widget
            else:
                widget = ctk.CTkEntry(self.form)
                widget.insert(0, value or "")
                self.entries[key] = widget
            widget.grid(row=row + 1, column=0, sticky="ew", padx=8)
            row += 2
        self.form.grid_columnconfigure(0, weight=1)
        self.error = ctk.CTkLabel(self, text="", text_color="#b42318", wraplength=560)
        self.error.grid(row=3, column=0, padx=24, sticky="w")
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, padx=18, pady=18, sticky="e")
        ctk.CTkButton(buttons, text="Cancelar", fg_color="transparent", border_width=1,
                      text_color=("#273840", "#e6eeee"), command=self.destroy).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Guardar expediente", command=self._save).pack(side="left", padx=6)

    @staticmethod
    def _set_entry(entry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _save(self):
        values = {key: widget.get() for key, widget in self.entries.items()}
        values.update({key: widget.get("1.0", "end").strip() for key, widget in self.texts.items()})
        if not values.get("date_of_birth"):
            values["date_of_birth"] = None
        try:
            if self.patient:
                self.service.update(self.patient.id, values)
            else:
                self.service.register(values)
            self.on_saved()
            self.destroy()
        except Exception as exc:
            self.error.configure(text=str(exc))


class ConsentDialog(ctk.CTkToplevel):
    def __init__(self, master, service: PatientService, patient: Patient, on_saved):
        super().__init__(master)
        self.service, self.patient, self.on_saved = service, patient, on_saved
        self.title("Consentimiento de publicación")
        self.geometry("520x650")
        self.transient(master)
        self.grab_set()
        ctk.CTkLabel(self, text="Información que podrá ser pública", font=ctk.CTkFont(size=21, weight="bold"),
                     wraplength=450).pack(anchor="w", padx=24, pady=(24, 8))
        ctk.CTkLabel(self, text="GitHub Pages es público. Un UUID no es un mecanismo de acceso privado.",
                     text_color="#9b3f28", wraplength=450, justify="left").pack(anchor="w", padx=24, pady=(0, 14))
        previous = {}
        try:
            import json
            candidate = json.loads(patient.consent_json).get("fields", [])
            previous = candidate if isinstance(candidate, list) and all(
                isinstance(item, str) and item in PUBLIC_FIELDS for item in candidate
            ) else []
        except (ValueError, AttributeError):
            pass
        self.fields = {}
        labels = {
            "full_name": "Nombre completo", "date_of_birth": "Fecha de nacimiento", "blood_type": "Tipo de sangre",
            "allergies": "Alergias", "conditions": "Padecimientos", "medications": "Medicamentos",
            "additional_information": "Información adicional", "emergency_contact_name": "Contacto de emergencia",
            "emergency_contact_relationship": "Parentesco", "emergency_contact_phone": "Teléfono de emergencia",
            "emergency_contact_2_name": "Contacto 2 · Nombre",
            "emergency_contact_2_relationship": "Contacto 2 · Parentesco",
            "emergency_contact_2_phone": "Contacto 2 · Teléfono",
            "emergency_contact_3_name": "Contacto 3 · Nombre",
            "emergency_contact_3_relationship": "Contacto 3 · Parentesco",
            "emergency_contact_3_phone": "Contacto 3 · Teléfono",
        }
        self.field_frame = ctk.CTkScrollableFrame(self, height=310, fg_color="transparent")
        self.field_frame.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        for field in sorted(PUBLIC_FIELDS):
            var = ctk.BooleanVar(value=field in previous)
            self.fields[field] = var
            ctk.CTkCheckBox(self.field_frame, text=labels[field], variable=var).pack(anchor="w", padx=12, pady=4)
        self.ack = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Confirmo que estoy autorizado para guardar estos cambios de consentimiento.",
                        variable=self.ack, wraplength=440).pack(anchor="w", padx=24, pady=(16, 8))
        self.error = ctk.CTkLabel(self, text="", text_color="#b42318", wraplength=450)
        self.error.pack(anchor="w", padx=24)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=20)
        ctk.CTkButton(buttons, text="Revocar autorización", fg_color="#9b3f28", command=self._revoke).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="Guardar selección", command=self._save).pack(side="right", padx=6)

    def _save(self):
        try:
            self.service.set_consent(
                self.patient.id, granted=True, fields=[key for key, var in self.fields.items() if var.get()],
                acknowledged=self.ack.get(), recorded_by="Interfaz local",
            )
            self.on_saved()
            self.destroy()
        except Exception as exc:
            self.error.configure(text=str(exc))

    def _revoke(self):
        try:
            self.service.set_consent(self.patient.id, granted=False, acknowledged=self.ack.get(),
                                     recorded_by="Interfaz local", note="Revocación desde la aplicación")
            self.on_saved()
            self.destroy()
        except Exception as exc:
            self.error.configure(text=str(exc))
