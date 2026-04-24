"""finish tool — declares the agent is done; orchestrator runs verify after."""
from __future__ import annotations

from apr_agent.tools.registry import Tool, ToolResult


class FinishTool(Tool):
    terminates_loop = True

    @property
    def name(self) -> str:
        return "finish"

    @property
    def description(self) -> str:
        return (
            "Declare that the bug is fixed. Provide a short rationale describing "
            "what was changed and why."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "rationale": {
                    "type": "string",
                    "description": "Short rationale for the fix.",
                },
            },
            "required": ["rationale"],
        }

    def invoke(self, arguments: dict) -> ToolResult:
        return ToolResult(output="", meta={"rationale": arguments.get("rationale", "")})
