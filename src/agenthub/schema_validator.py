from __future__ import annotations

import jsonschema

from .models import SkillConfig, ValidationResult


class SchemaValidator:
    MAX_RETRIES: int = 3

    def validate(self, output: dict, skill_config: SkillConfig, attempt: int = 0) -> ValidationResult:
        """按角色 output_schema 验证输出结构，返回 ValidationResult"""
        try:
            jsonschema.validate(instance=output, schema=skill_config.output_schema)
            return ValidationResult(ok=True, attempt=attempt)
        except jsonschema.ValidationError as e:
            return ValidationResult(ok=False, errors=[e.message], attempt=attempt)
        except jsonschema.SchemaError as e:
            return ValidationResult(ok=False, errors=[f"Invalid schema: {e.message}"], attempt=attempt)
