from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TransitionRequest(BaseModel):
    """Request payload for status transitions.

    Status is always transmitted as the enum.value string.
    """

    model_config = ConfigDict(extra="forbid")

    to_status: str = Field(min_length=1)
