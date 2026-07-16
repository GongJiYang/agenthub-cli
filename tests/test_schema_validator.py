"""Unit tests for SchemaValidator."""
import pytest

from agenthub.models import SkillConfig, ValidationResult
from agenthub.schema_validator import SchemaValidator

# contributor 角色的 output_schema（来自任务规范）
CONTRIBUTOR_SCHEMA = {
    "type": "object",
    "required": ["status", "summary", "files_changed"],
    "properties": {
        "status": {"type": "string", "enum": ["submitted"]},
        "summary": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
    },
}


def make_skill_config(schema: dict) -> SkillConfig:
    return SkillConfig(
        role="contributor",
        system_prompt_template="",
        tool_whitelist=[],
        path_rules=[],
        output_schema=schema,
    )


@pytest.fixture
def validator():
    return SchemaValidator()


@pytest.fixture
def skill():
    return make_skill_config(CONTRIBUTOR_SCHEMA)


class TestSchemaValidatorConstants:
    def test_max_retries(self):
        assert SchemaValidator.MAX_RETRIES == 3


class TestValidOutput:
    def test_valid_output_returns_ok_true(self, validator, skill):
        output = {
            "status": "submitted",
            "summary": "Fixed the bug",
            "files_changed": ["src/main.py"],
        }
        result = validator.validate(output, skill)
        assert result.ok is True

    def test_valid_output_errors_empty(self, validator, skill):
        output = {
            "status": "submitted",
            "summary": "Done",
            "files_changed": [],
        }
        result = validator.validate(output, skill)
        assert result.errors == []

    def test_valid_output_with_multiple_files(self, validator, skill):
        output = {
            "status": "submitted",
            "summary": "Refactored",
            "files_changed": ["a.py", "b.py", "c.py"],
        }
        result = validator.validate(output, skill)
        assert result.ok is True


class TestInvalidOutput:
    def test_invalid_output_returns_ok_false(self, validator, skill):
        result = validator.validate({}, skill)
        assert result.ok is False

    def test_invalid_output_errors_nonempty(self, validator, skill):
        result = validator.validate({}, skill)
        assert len(result.errors) > 0

    def test_wrong_status_enum_returns_ok_false(self, validator, skill):
        output = {
            "status": "pending",  # not in enum
            "summary": "Done",
            "files_changed": [],
        }
        result = validator.validate(output, skill)
        assert result.ok is False
        assert len(result.errors) > 0

    def test_wrong_type_files_changed(self, validator, skill):
        output = {
            "status": "submitted",
            "summary": "Done",
            "files_changed": "not-an-array",  # should be array
        }
        result = validator.validate(output, skill)
        assert result.ok is False
        assert len(result.errors) > 0


class TestMissingRequiredFields:
    def test_missing_status_errors_contain_field_info(self, validator, skill):
        output = {"summary": "Done", "files_changed": []}
        result = validator.validate(output, skill)
        assert result.ok is False
        assert any("status" in err for err in result.errors)

    def test_missing_summary_errors_contain_field_info(self, validator, skill):
        output = {"status": "submitted", "files_changed": []}
        result = validator.validate(output, skill)
        assert result.ok is False
        assert any("summary" in err for err in result.errors)

    def test_missing_files_changed_errors_contain_field_info(self, validator, skill):
        output = {"status": "submitted", "summary": "Done"}
        result = validator.validate(output, skill)
        assert result.ok is False
        assert any("files_changed" in err for err in result.errors)


class TestAttemptPropagation:
    def test_attempt_default_zero(self, validator, skill):
        result = validator.validate({"status": "submitted", "summary": "x", "files_changed": []}, skill)
        assert result.attempt == 0

    def test_attempt_passed_through_on_success(self, validator, skill):
        output = {"status": "submitted", "summary": "x", "files_changed": []}
        result = validator.validate(output, skill, attempt=2)
        assert result.attempt == 2

    def test_attempt_passed_through_on_failure(self, validator, skill):
        result = validator.validate({}, skill, attempt=1)
        assert result.attempt == 1

    def test_attempt_max_retries_value(self, validator, skill):
        result = validator.validate({}, skill, attempt=SchemaValidator.MAX_RETRIES)
        assert result.attempt == SchemaValidator.MAX_RETRIES
