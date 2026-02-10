from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class Error(BaseModel):
    """
    MVP domain object: one model error example.
    No DB here. No API here. Just the data contract + invariants.
    """

    y_true: str = Field(min_length=1)                  # правильный ответ
    y_pred: str = Field(min_length=1)                  # предсказание модели
    confidence: float = Field(ge=0.0, le=1.0)          # уверенность 0..1

    # опционально (потом пригодится для UI / дебага / ссылок на данные)
    example_ref: Optional[str] = None                  # путь/URL/хэш на пример
    slice: Optional[Dict[str, Any]] = None             # метаданные среза (device/country/...)

    @field_validator("example_ref")
    @classmethod
    def empty_string_to_none(cls, v: Optional[str]) -> Optional[str]:
        # чтобы не тащить пустые строки как "значение"
        if v is not None and v.strip() == "":
            return None
        return v
