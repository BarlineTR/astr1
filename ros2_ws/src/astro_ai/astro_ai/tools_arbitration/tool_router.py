"""ASTRO V1 — Tool Arbitration and Execution Router."""

from typing import Any, Callable, Dict, Optional

from astro_ai.tools_arbitration.safety_guard import ToolSafetyGuard


class ToolArbitrator:
    """Arbitrates and routes tool executions through safety validations and handlers."""

    def __init__(self):
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def register_handler(
        self, tool_name: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    ):
        self._handlers[tool_name] = handler

    def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validates safety and invokes the registered handler."""
        valid, reason = ToolSafetyGuard.validate_tool_call(tool_name, arguments)
        if not valid:
            return {
                "status": "rejected",
                "error": f"Security violation: {reason}",
                "tool": tool_name,
            }

        handler = self._handlers.get(tool_name)
        if not handler:
            return {
                "status": "error",
                "error": f"No handler registered for tool '{tool_name}'",
                "tool": tool_name,
            }

        try:
            res = handler(arguments)
            return {"status": "success", "result": res, "tool": tool_name}
        except Exception as exc:
            return {
                "status": "error",
                "error": f"Execution error in {tool_name}: {exc}",
                "tool": tool_name,
            }
