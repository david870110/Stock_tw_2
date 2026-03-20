import json
import re
from typing import Optional, Dict, Any, List
from src.models.log_entry import AgentRole
from src.models.task import QAResult


class ParsedResponse:
    def __init__(self, data: Dict[str, Any], raw: str, success: bool = True, error: Optional[str] = None):
        self.data = data
        self.raw = raw
        self.success = success
        self.error = error


class ResponseParser:
    """Parses agent responses. Tries JSON first, then markdown fallback."""

    def parse(self, raw: str, role: AgentRole) -> ParsedResponse:
        """Parse raw agent response into structured data."""
        # Try direct JSON parse
        data = self._extract_json(raw)
        if data is not None:
            return ParsedResponse(data=data, raw=raw, success=True)

        # Fallback to role-specific minimal response
        fallback = self._fallback_response(role, raw)
        return ParsedResponse(data=fallback, raw=raw, success=False, error="Could not parse JSON from response")

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Try to extract JSON from text, including from markdown code blocks."""
        # Try direct JSON parse first
        stripped = text.strip()
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting from markdown code blocks (```json ... ``` or ``` ... ```)
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'\{[\s\S]*\}',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    result = json.loads(match.strip())
                    if isinstance(result, dict):
                        return result
                except (json.JSONDecodeError, ValueError):
                    continue

        return None

    def _fallback_response(self, role: AgentRole, raw: str) -> Dict[str, Any]:
        """Return a minimal valid response structure for a given role."""
        if role == AgentRole.MANAGER:
            return {
                "tasks": [],
                "decision": "approve_spec",
                "instruction": raw[:500] if raw else "",
            }
        elif role == AgentRole.PLANNER:
            return {
                "spec": raw[:2000] if raw else "",
                "sections": [],
                "ready_for_coder": False,
            }
        elif role == AgentRole.CODER:
            return {
                "implementation_log": raw[:1000] if raw else "",
                "files_modified": [],
                "success": False,
            }
        elif role == AgentRole.QA:
            return {
                "result": "FAIL",
                "findings": ["Could not parse QA response"],
                "summary": raw[:500] if raw else "",
            }
        else:
            return {"raw": raw}

    def extract_qa_result(self, parsed: ParsedResponse) -> Optional[QAResult]:
        """Extract QA result enum from parsed response."""
        result_str = parsed.data.get("result")
        if result_str is None:
            return None
        try:
            return QAResult(result_str.upper())
        except ValueError:
            return None

    def extract_tasks_from_manager(self, parsed: ParsedResponse) -> List[Dict[str, Any]]:
        """Extract task list from manager parsed response."""
        return parsed.data.get("tasks", [])
