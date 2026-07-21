"""Simple model router for LLM calls."""

from engine.config import get_engine_config


def route_model(task: str, default_model: str) -> str:
    cfg = get_engine_config().get("model_router", {})
    mapping = cfg.get("task_to_model", {})
    return mapping.get(task, default_model)
