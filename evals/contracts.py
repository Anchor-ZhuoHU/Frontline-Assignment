from __future__ import annotations

import ast
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


ROOM1_SCHEMA_NAMES = (
    "VERIFY_CARRIER_FUNCTION",
    "GET_LOAD_CONTEXT_FUNCTION",
    "RECORD_AGREEMENT_FUNCTION",
    "END_CALL_FUNCTION",
    "TRANSFER_TO_HUMAN_FUNCTION",
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_prompt_module(repo_root: Path) -> ModuleType:
    saved = {
        name: sys.modules.get(name)
        for name in ("src", "src.negotiation_prompt", "_frontline_voice_prompt")
    }
    try:
        src_stub = types.ModuleType("src")
        src_stub.__path__ = []
        sys.modules["src"] = src_stub
        negotiation = _load_module(
            "src.negotiation_prompt",
            repo_root / "shared" / "src" / "negotiation_prompt.py",
        )
        src_stub.negotiation_prompt = negotiation
        return _load_module(
            "_frontline_voice_prompt", repo_root / "voice-agent" / "voice_prompt.py"
        )
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _schema_from_call(call: ast.Call, path: Path) -> dict[str, Any]:
    values = {}
    for keyword in call.keywords:
        if keyword.arg in {"name", "description", "properties", "required"}:
            try:
                values[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"non-literal FunctionSchema {keyword.arg} in {path}"
                ) from exc
    missing = {"name", "description", "properties", "required"} - values.keys()
    if missing:
        raise ValueError(f"FunctionSchema in {path} is missing {sorted(missing)}")
    return {
        "type": "function",
        "function": {
            "name": values["name"],
            "description": values["description"],
            "parameters": {
                "type": "object",
                "properties": values["properties"],
                "required": values["required"],
            },
        },
    }


def _load_room1_schemas(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in ROOM1_SCHEMA_NAMES:
            continue
        if not isinstance(node.value, ast.Call):
            raise ValueError(f"{target.id} is not a FunctionSchema call in {path}")
        found[target.id] = _schema_from_call(node.value, path)
    missing = [name for name in ROOM1_SCHEMA_NAMES if name not in found]
    if missing:
        raise ValueError(f"missing Room 1 schemas in {path}: {missing}")
    return [found[name] for name in ROOM1_SCHEMA_NAMES]


@dataclass(frozen=True)
class ProductionContracts:
    initial_prompt: Callable[..., str]
    negotiation_prompt: Callable[[dict[str, Any]], str]
    room1_tools: list[dict[str, Any]]

    @classmethod
    def load(cls, repo_root: Path) -> "ProductionContracts":
        prompt_module = _load_prompt_module(repo_root)
        return cls(
            initial_prompt=prompt_module.get_initial_greeting_prompt,
            negotiation_prompt=prompt_module.build_full_negotiation_prompt,
            room1_tools=_load_room1_schemas(
                repo_root / "voice-agent" / "tool_definitions.py"
            ),
        )

