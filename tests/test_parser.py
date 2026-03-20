import json
import pytest
from src.parsing.parser import ResponseParser, ParsedResponse
from src.models.log_entry import AgentRole
from src.models.task import QAResult


class TestResponseParser:
    def setup_method(self):
        self.parser = ResponseParser()

    def test_valid_json_parsing(self):
        raw = json.dumps({"result": "PASS", "findings": [], "summary": "All good"})
        parsed = self.parser.parse(raw, AgentRole.QA)
        assert parsed.success is True
        assert parsed.data["result"] == "PASS"

    def test_json_in_markdown_code_block(self):
        raw = '```json\n{"result": "FAIL", "findings": ["bug found"], "summary": "Issues found"}\n```'
        parsed = self.parser.parse(raw, AgentRole.QA)
        assert parsed.success is True
        assert parsed.data["result"] == "FAIL"

    def test_json_in_plain_code_block(self):
        raw = '```\n{"spec": "test spec", "sections": [], "ready_for_coder": true}\n```'
        parsed = self.parser.parse(raw, AgentRole.PLANNER)
        assert parsed.success is True
        assert parsed.data["spec"] == "test spec"

    def test_invalid_json_fallback_manager(self):
        raw = "This is not JSON at all"
        parsed = self.parser.parse(raw, AgentRole.MANAGER)
        assert parsed.success is False
        assert "tasks" in parsed.data
        assert "decision" in parsed.data

    def test_invalid_json_fallback_planner(self):
        raw = "This is not JSON at all"
        parsed = self.parser.parse(raw, AgentRole.PLANNER)
        assert parsed.success is False
        assert "spec" in parsed.data
        assert "ready_for_coder" in parsed.data

    def test_invalid_json_fallback_coder(self):
        raw = "This is not JSON at all"
        parsed = self.parser.parse(raw, AgentRole.CODER)
        assert parsed.success is False
        assert "implementation_log" in parsed.data
        assert "success" in parsed.data

    def test_invalid_json_fallback_qa(self):
        raw = "This is not JSON at all"
        parsed = self.parser.parse(raw, AgentRole.QA)
        assert parsed.success is False
        assert "result" in parsed.data
        assert parsed.data["result"] == "FAIL"

    def test_extract_qa_result_pass(self):
        raw = json.dumps({"result": "PASS", "findings": [], "summary": ""})
        parsed = self.parser.parse(raw, AgentRole.QA)
        result = self.parser.extract_qa_result(parsed)
        assert result == QAResult.PASS

    def test_extract_qa_result_fail(self):
        raw = json.dumps({"result": "FAIL", "findings": ["bug"], "summary": ""})
        parsed = self.parser.parse(raw, AgentRole.QA)
        result = self.parser.extract_qa_result(parsed)
        assert result == QAResult.FAIL

    def test_extract_qa_result_spec_gap(self):
        raw = json.dumps({"result": "SPEC_GAP", "findings": ["gap"], "summary": ""})
        parsed = self.parser.parse(raw, AgentRole.QA)
        result = self.parser.extract_qa_result(parsed)
        assert result == QAResult.SPEC_GAP

    def test_extract_qa_result_missing(self):
        parsed = ParsedResponse(data={}, raw="", success=False)
        result = self.parser.extract_qa_result(parsed)
        assert result is None

    def test_extract_tasks_from_manager(self):
        tasks_data = [
            {"title": "Task 1", "description": "Desc 1", "priority": "HIGH", "acceptance_criteria": ["AC1"]},
            {"title": "Task 2", "description": "Desc 2", "priority": "LOW", "acceptance_criteria": []},
        ]
        raw = json.dumps({"tasks": tasks_data, "decision": "approve_spec", "instruction": "Go ahead"})
        parsed = self.parser.parse(raw, AgentRole.MANAGER)
        tasks = self.parser.extract_tasks_from_manager(parsed)
        assert len(tasks) == 2
        assert tasks[0]["title"] == "Task 1"
        assert tasks[1]["title"] == "Task 2"

    def test_extract_tasks_empty(self):
        raw = json.dumps({"tasks": [], "decision": "approve_spec", "instruction": ""})
        parsed = self.parser.parse(raw, AgentRole.MANAGER)
        tasks = self.parser.extract_tasks_from_manager(parsed)
        assert tasks == []
