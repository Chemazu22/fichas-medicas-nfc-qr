"""Diálogos para registrar, editar y autorizar expedientes."""

from __future__ import annotations

import customtkinter as ctk

from fichas_medicas.database.models import Patient
from fichas_medicas.services.patient_service import PUBLIC_FIELDS, PatientService


class PatientFormDialog(ctk.CTkToplevel):
    def __init__(self, master, service: PatientService, on_saved, patient: Patient | None = None):
        super().__init__(master)
        self.service, self.on_saved, self.patient = service, on_saved, patient
        self.title("Editar expediente" if patient else "Registrar persona")
        self.geometry("640x760")
        self.minsize(540, 620)
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
            ("date_of_birth", "Fecha de nacimiento (AAAA-MM-DD)", "entry"),
            ("blood_type", "Tipo de sangre", "blood"),
            ("allergies", "Alergias", "text"),
            ("conditions", "Padecimientos", "text"),
            ("medications", "Medicamentos", "text"),
            ("additional_information", "Información adicional", "text"),
            ("emergency_contact_name", "Contacto de emergencia", "entry"),
            ("emergency_contact_relationship", "Parentesco", "entry"),
            ("emergency_contact_phone", "Teléfono de emergencia", "entry"),
        ]
        for key, label, kind in fields:
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
        }
        for field in sorted(PUBLIC_FIELDS):
            var = ctk.BooleanVar(value=field in previous)
            self.fields[field] = var
            ctk.CTkCheckBox(self, text=labels[field], variable=var).pack(anchor="w", padx=28, pady=4)
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
