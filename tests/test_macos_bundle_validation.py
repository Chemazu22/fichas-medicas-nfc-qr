from __future__ import annotations

from scripts.validate_macos_bundle import _find_private_artifacts


def test_bundle_privacy_scan_finds_database_and_generated_uuid_files(tmp_path):
    (tmp_path / "fichas_medicas.sqlite3").write_bytes(b"private")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "backup.sqlite3").write_bytes(b"private")
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources" / "12345678-1234-4234-8234-123456789abc.html").write_text("profile")
    (tmp_path / "resources" / "12345678-1234-4234-8234-123456789abc.png").write_bytes(b"qr")

    violations = set(_find_private_artifacts(tmp_path))

    assert violations == {
        "fichas_medicas.sqlite3",
        "backups/backup.sqlite3",
        "resources/12345678-1234-4234-8234-123456789abc.html",
        "resources/12345678-1234-4234-8234-123456789abc.png",
    }


def test_bundle_privacy_scan_allows_generic_templates(tmp_path):
    templates = tmp_path / "fichas_medicas" / "templates"
    templates.mkdir(parents=True)
    (templates / "medical_profile.html").write_text("generic template")
    (templates / "styles.css").write_text("body {}")

    assert _find_private_artifacts(tmp_path) == []
