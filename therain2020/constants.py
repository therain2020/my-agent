"""Centralised constants — no magic numbers scattered across modules."""

import os
from pathlib import Path

# Agent behaviour
MAX_STEPS: int = 5
MAX_CONVERSATION_MESSAGES: int = 40

# Provider
DEFAULT_MAX_TOKENS: int = 4096

# Memory
MEMORY_DB_FILENAME: str = "memory.db"
SEMANTIC_SEARCH_LIMIT: int = 10
RECENT_EPISODES_LIMIT: int = 5

# Workspace
WORKSPACE_DIR: Path = Path(
    os.environ.get("TRAIN2020_WORKSPACE", Path.cwd() / ".agent")
)

# Safety
DONT_DO_HOOKS: tuple[str, ...] = ("PLAN", "PRE_ACTION", "POST_ACTION")
