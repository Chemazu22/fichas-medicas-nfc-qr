"""Codificación de salida segura para contenido que se insertará en HTML."""

from __future__ import annotations

import html
import re

from fichas_medicas.security.validation import ValidationError

_TEL_ALLOWED = re.compile(r"^[0-9+().\-\s]*$")


def escape_html(value: object | None) -> str:
    """Escapa texto para un nodo HTML. No reemplaza la validación del dominio."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def telephone_href(value: str) -> str:
    """Normaliza un teléfono ya validado para usarlo en href=\"tel:...\"."""
    if not isinstance(value, str) or not _TEL_ALLOWED.fullmatch(value):
        raise ValidationError("El teléfono contiene caracteres no válidos para un enlace de llamada.")
    compact = "".join(char for char in value if not char.isspace() and char not in "().-")
    if compact.count("+") > 1 or ("+" in compact and not compact.startswith("+")):
        raise ValidationError("El prefijo + solo puede aparecer al inicio del teléfono.")
    digits = "".join(char for char in value if char.isdigit())
    if not 7 <= len(digits) <= 15:
        raise ValidationError("El teléfono debe contener entre 7 y 15 dígitos.")
    return f"tel:{compact}"
