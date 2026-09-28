from pathlib import Path

from app.config import Settings
from app.scenarios import SCENARIO_DISCLAIMER

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_legal_human_review_checklist_exists() -> None:
    checklist = REPO_ROOT / "LEGAL_HUMAN_REVIEW.md"
    assert checklist.is_file(), "LEGAL_HUMAN_REVIEW.md must exist at repository root"
    content = checklist.read_text(encoding="utf-8")
    assert "[REQUIRES HUMAN INPUT — OPERATOR LEGAL NAME]" in content
    assert "[REQUIRES HUMAN INPUT — OPERATOR PHYSICAL ADDRESS]" in content
    assert "[REQUIRES HUMAN INPUT — PRIVACY CONTACT EMAIL / FORM]" in content
    assert "[REQUIRES HUMAN INPUT — SECURITY CONTACT EMAIL]" in content
    assert "[REQUIRES HUMAN INPUT — COPYRIGHT CONTACT EMAIL]" in content
    assert "DOCUMENT_RETENTION_DAYS" in content
    assert "WORKSPACE_GRACE_HOURS" in content


def test_scenario_disclaimer_is_non_empty_and_factual() -> None:
    assert "not forecasts or investment recommendations" in SCENARIO_DISCLAIMER


def test_settings_retention_defaults_match_documentation() -> None:
    # Verify the code defaults documented in Privacy Policy and SECURITY.md
    # Use dummy valid settings for instantiate test
    fields = Settings.model_fields
    assert fields["document_retention_days"].default == 30
    assert fields["workspace_grace_hours"].default == 24
    assert fields["failed_document_retention_hours"].default == 24
    assert fields["max_upload_bytes"].default == 50 * 1024 * 1024
