"""ASTRO V1 — Architecture Context Builder.

Extracts minimal, high-salience architectural context for support layer queries
without dumping full repository files into external model contexts.

KEY INVARIANTS:
  1. Never loads the entire repository.
  2. Never exposes protected files (.env, secrets, *.db, .git, hardware controllers).
  3. Enforces a hard token budget per request; reduces or summarizes when necessary.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from astro_ai.brain.support.config import SupportConfig

PROTECTED_PATTERNS = [
    r"\.env",
    r"\.git",
    r"\.db$",
    r"astro_cognitive\.db",
    r"secrets?",
    r"key",
    r"token",
    r"password",
    r"credential",
    r"motors?",
    r"actuators?",
    r"hardware_drivers?",
]

AUTHORIZED_DIRECTORIES = [
    os.path.normpath("ros2_ws/src/astro_ai/astro_ai/brain"),
    os.path.normpath("ros2_ws/src/astro_ai/astro_ai/contracts"),
    os.path.normpath("ros2_ws/src/astro_ai/test"),
]

AUTHORIZED_FILES = [
    os.path.normpath("ros2_ws/src/astro_ai/astro_ai/consciousness_node.py"),
]


class TokenBudgetExceededError(ValueError):
    """Raised when context exceeds the maximum allowed token budget."""
    pass


class ArchitectureContextBuilder:
    """Builds minimized, topic-scoped architectural context snippets."""

    def __init__(self, workspace_root: Optional[str] = None, config: Optional[SupportConfig] = None):
        self.workspace_root = workspace_root if workspace_root is not None else os.getcwd()
        self.config = config if config is not None else SupportConfig.from_env()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimator (~4 characters per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def is_protected_file(self, rel_path: str) -> bool:
        """Checks whether a file matches protected or secret patterns."""
        norm = os.path.normpath(rel_path).replace("\\", "/")
        for pattern in PROTECTED_PATTERNS:
            if re.search(pattern, norm, re.IGNORECASE):
                return True
        return False

    def is_authorized_file(self, rel_path: str) -> bool:
        """Verifies whether a file is within explicitly authorized consciousness areas."""
        if self.is_protected_file(rel_path):
            return False

        abs_target = os.path.abspath(os.path.join(self.workspace_root, rel_path))
        norm_target = os.path.normpath(abs_target)

        # Check authorized individual files
        for auth_file in AUTHORIZED_FILES:
            abs_auth = os.path.abspath(os.path.join(self.workspace_root, auth_file))
            if norm_target == abs_auth:
                return True

        # Check authorized directories
        for auth_dir in AUTHORIZED_DIRECTORIES:
            abs_auth_dir = os.path.abspath(os.path.join(self.workspace_root, auth_dir))
            if norm_target.startswith(abs_auth_dir):
                return True

        return False

    def _read_file_safely(self, rel_path: str, max_lines: int = 150) -> Optional[str]:
        """Safely reads file excerpt if authorized, returning None if unauthorized/missing."""
        if not self.is_authorized_file(rel_path):
            return None

        full_path = os.path.join(self.workspace_root, rel_path)
        if not os.path.isfile(full_path):
            return None

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
            return "".join(lines)
        except Exception:
            return None

    def build_context(
        self,
        topic: str,
        target_files: Optional[List[str]] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Builds minimized context for the requested topic.

        Returns:
            (context_text, metadata_dict)
        """
        budget = max_tokens if max_tokens is not None else self.config.gemini_max_input_tokens
        collected_snippets: List[str] = []
        files_included: List[str] = []

        top = topic.lower().strip()

        if top in ("self_model", "self_state", "introspection"):
            files_to_read = [
                "ros2_ws/src/astro_ai/astro_ai/brain/self_model.py",
                "ros2_ws/src/astro_ai/astro_ai/contracts/consciousness_types.py",
            ]
        elif top in ("affective_state", "affect", "modulator"):
            files_to_read = [
                "ros2_ws/src/astro_ai/astro_ai/brain/affective_state.py",
                "ros2_ws/src/astro_ai/astro_ai/contracts/consciousness_types.py",
            ]
        elif top in ("cognitive_loop", "loop", "temporal"):
            files_to_read = [
                "ros2_ws/src/astro_ai/astro_ai/brain/cognitive_loop.py",
                "ros2_ws/src/astro_ai/astro_ai/brain/cognitive_event_bus.py",
            ]
        elif top in ("goal", "goals", "planning"):
            files_to_read = [
                "ros2_ws/src/astro_ai/astro_ai/contracts/consciousness_types.py",
            ]
        else:
            files_to_read = target_files or [
                "ros2_ws/src/astro_ai/astro_ai/contracts/consciousness_types.py",
                "ros2_ws/src/astro_ai/astro_ai/brain/self_model.py",
            ]

        # Ingest designated files
        for rel_path in files_to_read:
            content = self._read_file_safely(rel_path, max_lines=120)
            if content:
                files_included.append(rel_path)
                header = f"\n=== File: {rel_path} (Truncated Excerpt) ===\n"
                collected_snippets.append(header + content)

        raw_context = "\n".join(collected_snippets)
        estimated_tokens = self.estimate_tokens(raw_context)

        # Budget enforcement: If over budget, compress by keeping signatures and docstrings
        if estimated_tokens > budget:
            compressed_lines = []
            for line in raw_context.splitlines():
                if any(line.strip().startswith(kw) for kw in ("class ", "def ", '"""', "@dataclass", "@", "#")):
                    compressed_lines.append(line)
            raw_context = "\n".join(compressed_lines)
            estimated_tokens = self.estimate_tokens(raw_context)

            # If still exceeds budget, raise TokenBudgetExceededError
            if estimated_tokens > budget:
                raise TokenBudgetExceededError(
                    f"Context token count ({estimated_tokens}) exceeds maximum budget ({budget}) after compression."
                )

        context_hash = hashlib.sha256(raw_context.encode("utf-8")).hexdigest()

        metadata = {
            "topic": topic,
            "files_included": files_included,
            "estimated_tokens": estimated_tokens,
            "context_hash": context_hash,
            "is_compressed": len(collected_snippets) > 0 and (len(raw_context) < sum(len(s) for s in collected_snippets)),
        }

        return raw_context, metadata
