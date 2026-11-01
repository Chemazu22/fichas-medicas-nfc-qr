"""Estado local de última publicación, sin incluir nombres ni datos médicos."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from fichas_medicas.config.paths import data_directory

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_VALID_STATES = {"published", "pending_publish", "pending_update", "pending_removal", "removed"}


class PublicationStateStore:
    """Guarda un índice UUID/estado local, fuera del checkout que sirve Pages."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else data_directory() / "publication_state.json"

    def all(self) -> dict[str, str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {key: value for key, value in raw.items()
                if isinstance(key, str) and _UUID.fullmatch(key)
                and isinstance(value, str) and value in _VALID_STATES}

    def get(self, patient_uuid: str) -> str | None:
        return self.all().get(patient_uuid)

    def set(self, patient_uuid: str, state: str) -> None:
        if not _UUID.fullmatch(patient_uuid) or state not in _VALID_STATES:
            raise ValueError("UUID o estado de publicación no válido.")
        states = self.all()
        states[patient_uuid] = state
        self.replace(states)

    def remove(self, patient_uuid: str) -> None:
        states = self.all()
        if patient_uuid in states:
            del states[patient_uuid]
            self.replace(states)

    def replace(self, states: dict[str, str]) -> None:
        clean = {key: value for key, value in states.items()
                 if _UUID.fullmatch(key) and value in _VALID_STATES}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        fd, temporary_name = tempfile.mkstemp(prefix=".publication-state-", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(clean, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
