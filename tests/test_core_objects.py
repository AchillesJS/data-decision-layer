import pytest
from pydantic import ValidationError

from core.error import Error


def test_error_ok():
    e = Error(y_true="cat", y_pred="dog", confidence=0.7)
    assert e.confidence == 0.7


def test_error_confidence_bounds():
    with pytest.raises(ValidationError):
        Error(y_true="cat", y_pred="dog", confidence=1.5)
