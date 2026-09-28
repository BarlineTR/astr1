"""ASTRO V1 — Hard Safety Boundaries and Tool Argument Validation Guard."""

from typing import Any, Dict, List, Tuple


class ToolSafetyGuard:
    """Enforces strict safety verification, preventing dangerous physical actions or shell execution."""

    FORBIDDEN_TOOLS = {
        "exec_shell", "run_command", "delete_system_file", "raw_motor_write",
        "shutdown_host", "format_disk", "write_raw_memory"
    }

    FORBIDDEN_KEYWORDS = [
        "rm -rf", "sudo", "mkfs", ":(){ :|:& };:", "chmod 777 /", "> /dev/sda"
    ]

    @classmethod
    def validate_tool_call(
        cls,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Validates tool execution against hard safety boundaries."""
        if tool_name in cls.FORBIDDEN_TOOLS:
            return False, f"Tool '{tool_name}' is forbidden by hard safety policy."

        # Scan string arguments for malicious injections
        for key, val in arguments.items():
            if isinstance(val, str):
                v_low = val.lower()
                if any(bad in v_low for bad in cls.FORBIDDEN_KEYWORDS):
                    return False, f"Forbidden keyword detected in argument '{key}'."

        # Specific argument range validations
        if tool_name == "set_reminder":
            mins = arguments.get("minutes", 1.0)
            try:
                m_val = float(mins)
                if m_val <= 0.0 or m_val > 1440.0:  # max 24 hours
                    return False, f"Reminder minutes ({m_val}) out of valid range (0, 1440]."
            except (ValueError, TypeError):
                return False, "Invalid non-numeric value for minutes."

        return True, "valid"
