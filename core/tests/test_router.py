"""Tests for model router."""

from unittest.mock import patch

from engine.llm.router import route_model


def test_default():
    assert route_model("summarize", "default") == "default"


def test_mapped():
    with patch("engine.llm.router.get_engine_config") as m:
        m.return_value = {"model_router": {"task_to_model": {"classify": "tiny"}}}
        assert route_model("classify", "default") == "tiny"
