"""Configuración local sin credenciales ni tokens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fichas_medicas.config.paths import data_directory


class AppSettings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_directory() / "config.json"
        self.values: dict[str, Any] = {
            "public_base_url": "",
            "repository_dir": "",
            "remote_url": "",
            "appearance": "System",
        }
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(saved, dict):
            # Ignora llaves desconocidas para no introducir secretos arbitrarios.
            for key in self.values:
                if isinstance(saved.get(key), str):
                    self.values[key] = saved[key]

    def save(self, **changes: str) -> None:
        for key, value in changes.items():
            if key not in self.values or not isinstance(value, str):
                raise ValueError(f"Configuración no admitida: {key}")
            self.values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            temporary.chmod(0o600)
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        temporary.replace(self.path)
