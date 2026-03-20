import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from src.models.task import Task, TaskStatus, QAResult, TaskPriority
from src.models.log_entry import LogEntry, AgentRole
from src.agents.base import BaseAgentClient
from src.parsing.parser import ResponseParser
from src.storage.local_storage import LocalStorage
from src.prompts.loader import PromptLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


class OrchestratorConfig:
    def __init__(
        self,
        max_iterations: int = 5,
        max_retries: int = 3,
        storage_path: str = "runs",
        prompts_path: str = "prompts",
        parser_mode: str = "json",
    ):
        self.max_iterations = max_iterations
        self.max_retries = max_retries
        self.storage_path = storage_path
        self.prompts_path = prompts_path
        self.parser_mode = parser_mode


class OrchestratorEngine:
    def __init__(
        self,
        config: OrchestratorConfig,
        manager_client: BaseAgentClient,
        planner_client: BaseAgentClient,
        coder_client: BaseAgentClient,
        qa_client: BaseAgentClient,
    ):
        self.config = config
        self.manager_client = manager_client
        self.planner_client = planner_client
        self.coder_client = coder_client
        self.qa_client = qa_client
        self.storage = LocalStorage(config.storage_path)
        self.parser = ResponseParser()
        self.prompt_loader = PromptLoader(config.prompts_path)
        self.run_id = str(uuid.uuid4())

    def run(self, user_requirement: str) -> Dict[str, Any]:
        """Main entry point. Takes user requirement, runs full pipeline."""
        logger.info(f"Starting run {self.run_id} with requirement: {user_requirement[:100]}")

        # Step 1: Manager analyzes and breaks down tasks
        tasks = self._manager_plan(user_requirement)

        # Step 2: Execute each task
        results = []
        for task in tasks:
            result = self._execute_task(task)
            results.append(result)

        # Step 3: Generate final summary
        summary = self._generate_summary(results)
        self.storage.save_summary(self.run_id, summary)
        return summary

    def _manager_plan(self, user_requirement: str) -> List[Task]:
        """Call Manager to break user requirement into tasks."""
        logger.info("Manager planning tasks from user requirement")
        prompt = f"Analyze the following requirement and break it into tasks:\n\n{user_requirement}"
        response = self.manager_client.call(prompt)
        parsed = self.parser.parse(response.raw, AgentRole.MANAGER)

        task_dicts = self.parser.extract_tasks_from_manager(parsed)
        tasks = []

        if not task_dicts:
            # Fallback: create a single task from the requirement
            task = Task(
                title="Main Task",
                description=user_requirement,
                priority=TaskPriority.MEDIUM,
            )
            tasks.append(task)
        else:
            for td in task_dicts:
                priority_str = td.get("priority", "MEDIUM").upper()
                try:
                    priority = TaskPriority(priority_str)
                except ValueError:
                    priority = TaskPriority.MEDIUM

                task = Task(
                    title=td.get("title", "Unnamed Task"),
                    description=td.get("description", ""),
                    priority=priority,
                    acceptance_criteria=td.get("acceptance_criteria", []),
                )
                tasks.append(task)

        for task in tasks:
            task.transition_to(TaskStatus.MANAGER_PLANNING)
            self.storage.save_task(task)
            logger.info(f"Created task: {task.id} - {task.title}")

        return tasks

    def _execute_task(self, task: Task) -> Dict[str, Any]:
        """Execute a single task through the full pipeline with rerouting."""
        logger.info(f"Executing task {task.id}: {task.title}")

        for iteration in range(self.config.max_iterations):
            task.increment_iteration()
            logger.info(f"Task {task.id} iteration {task.iteration_count}")

            # Step 1: Manager generates planner instruction
            planner_instruction = self._get_planner_instruction(task)

            # Step 2: Planner creates spec
            task.transition_to(TaskStatus.WAIT_PLANNER)
            self.storage.save_task(task)
            planner_raw = self._call_planner(task, planner_instruction)
            planner_parsed = self.parser.parse(planner_raw, AgentRole.PLANNER)
            task.spec = planner_parsed.data.get("spec", planner_raw)
            task.transition_to(TaskStatus.PLANNER_DONE)
            self.storage.save_task(task)

            # Step 3: Manager reviews spec
            task.transition_to(TaskStatus.MANAGER_SPEC_REVIEW)
            self.storage.save_task(task)
            spec_decision = self._manager_review_spec(task)

            if spec_decision == "revise_spec":
                logger.info(f"Task {task.id}: Manager requested spec revision")
                # Loop back to planner in next iteration
                continue

            # Step 4: Manager generates coder instruction
            coder_instruction = self._get_coder_instruction(task)

            # Step 5: Coder implements
            task.transition_to(TaskStatus.WAIT_CODER)
            self.storage.save_task(task)
            coder_raw = self._call_coder(task, coder_instruction)
            coder_parsed = self.parser.parse(coder_raw, AgentRole.CODER)
            task.coder_log = coder_parsed.data.get("implementation_log", coder_raw)
            task.transition_to(TaskStatus.CODER_DONE)
            self.storage.save_task(task)

            # Step 6: Manager generates QA instruction
            qa_instruction = self._get_qa_instruction(task)

            # Step 7: QA validates
            task.transition_to(TaskStatus.WAIT_QA)
            self.storage.save_task(task)
            qa_raw = self._call_qa(task, qa_instruction)
            qa_parsed = self.parser.parse(qa_raw, AgentRole.QA)
            task.qa_log = qa_parsed.data.get("summary", qa_raw)
            task.transition_to(TaskStatus.QA_DONE)
            self.storage.save_task(task)

            # Step 8: Act on QA result
            qa_result = self.parser.extract_qa_result(qa_parsed)
            task.last_qa_result = qa_result

            if qa_result == QAResult.PASS:
                task.transition_to(TaskStatus.DONE)
                self.storage.save_task(task)
                logger.info(f"Task {task.id} DONE after {task.iteration_count} iteration(s)")
                return {
                    "task_id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "iterations": task.iteration_count,
                    "qa_result": qa_result.value if qa_result else None,
                }
            elif qa_result == QAResult.FAIL:
                logger.info(f"Task {task.id}: QA FAIL - rerouting to Coder")
                # Inline retry: skip Planner and go straight to Coder within the same iteration
                coder_instruction = self._get_coder_instruction(task, qa_feedback=task.qa_log)
                task.transition_to(TaskStatus.WAIT_CODER)
                self.storage.save_task(task)
                coder_raw = self._call_coder(task, coder_instruction)
                coder_parsed = self.parser.parse(coder_raw, AgentRole.CODER)
                task.coder_log = coder_parsed.data.get("implementation_log", coder_raw)
                task.transition_to(TaskStatus.CODER_DONE)

                # QA again
                task.transition_to(TaskStatus.WAIT_QA)
                self.storage.save_task(task)
                qa_raw = self._call_qa(task, qa_instruction)
                qa_parsed = self.parser.parse(qa_raw, AgentRole.QA)
                task.qa_log = qa_parsed.data.get("summary", qa_raw)
                task.transition_to(TaskStatus.QA_DONE)
                qa_result = self.parser.extract_qa_result(qa_parsed)
                task.last_qa_result = qa_result
                self.storage.save_task(task)

                if qa_result == QAResult.PASS:
                    task.transition_to(TaskStatus.DONE)
                    self.storage.save_task(task)
                    logger.info(f"Task {task.id} DONE after retry")
                    return {
                        "task_id": task.id,
                        "title": task.title,
                        "status": task.status.value,
                        "iterations": task.iteration_count,
                        "qa_result": qa_result.value if qa_result else None,
                    }
                continue
            elif qa_result == QAResult.SPEC_GAP:
                logger.info(f"Task {task.id}: QA SPEC_GAP - rerouting to Planner")
                # Continue main loop which will call planner again
                continue

        # Max iterations reached
        task.transition_to(TaskStatus.BLOCKED)
        self.storage.save_task(task)
        logger.warning(f"Task {task.id} BLOCKED after {task.iteration_count} iteration(s)")
        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "iterations": task.iteration_count,
            "qa_result": task.last_qa_result.value if task.last_qa_result else None,
        }

    def _get_planner_instruction(self, task: Task) -> str:
        """Generate planner instruction via Manager."""
        criteria_text = "\n".join(f"- {c}" for c in task.acceptance_criteria) or "- Complete the task"
        try:
            return self.prompt_loader.render_template(
                "manager_to_planner",
                title=task.title,
                description=task.description,
                priority=task.priority.value,
                acceptance_criteria=criteria_text,
            )
        except Exception:
            return f"Create a specification for: {task.title}\n\n{task.description}"

    def _get_coder_instruction(self, task: Task, qa_feedback: Optional[str] = None) -> str:
        """Generate coder instruction via Manager."""
        spec = task.spec or "No spec available"
        try:
            instruction = self.prompt_loader.render_template(
                "manager_to_coder",
                title=task.title,
                description=task.description,
                priority=task.priority.value,
                spec=spec,
            )
            if qa_feedback:
                instruction += f"\n\n## QA Feedback (Fix these issues):\n{qa_feedback}"
            return instruction
        except Exception:
            return f"Implement: {task.title}\n\nSpec: {spec}"

    def _get_qa_instruction(self, task: Task) -> str:
        """Generate QA instruction via Manager."""
        spec = task.spec or "No spec available"
        coder_log = task.coder_log or "No coder log available"
        try:
            return self.prompt_loader.render_template(
                "manager_to_qa",
                title=task.title,
                description=task.description,
                spec=spec,
                coder_log=coder_log,
            )
        except Exception:
            return f"Validate: {task.title}\n\nSpec: {spec}\n\nCoder Log: {coder_log}"

    def _manager_review_spec(self, task: Task) -> str:
        """Have Manager review the Planner's spec. Returns decision string."""
        prompt = (
            f"Review this spec for task '{task.title}':\n\n{task.spec}\n\n"
            "Is the spec complete and ready for the Coder? "
            'Respond with JSON: {"decision": "approve_spec"|"revise_spec", "instruction": "..."}'
        )
        response = self.manager_client.call(prompt)
        parsed = self.parser.parse(response.raw, AgentRole.MANAGER)
        return parsed.data.get("decision", "approve_spec")

    def _call_planner(self, task: Task, instruction: str) -> str:
        """Call Planner agent and save log."""
        logger.info(f"Calling Planner for task {task.id}")
        response = self.planner_client.call(instruction, context={"task_id": task.id})
        parsed = self.parser.parse(response.raw, AgentRole.PLANNER)
        self._save_log(
            task_id=task.id,
            role=AgentRole.PLANNER,
            raw=response.raw,
            parsed=parsed.data,
            status="SUCCESS" if parsed.success else "PARSE_ERROR",
            iteration=task.iteration_count,
        )
        return response.raw

    def _call_coder(self, task: Task, instruction: str) -> str:
        """Call Coder agent and save log."""
        logger.info(f"Calling Coder for task {task.id}")
        response = self.coder_client.call(instruction, context={"task_id": task.id, "spec": task.spec})
        parsed = self.parser.parse(response.raw, AgentRole.CODER)
        self._save_log(
            task_id=task.id,
            role=AgentRole.CODER,
            raw=response.raw,
            parsed=parsed.data,
            status="SUCCESS" if parsed.success else "PARSE_ERROR",
            iteration=task.iteration_count,
        )
        return response.raw

    def _call_qa(self, task: Task, instruction: str) -> str:
        """Call QA agent and save log."""
        logger.info(f"Calling QA for task {task.id}")
        response = self.qa_client.call(
            instruction, context={"task_id": task.id, "spec": task.spec, "coder_log": task.coder_log}
        )
        parsed = self.parser.parse(response.raw, AgentRole.QA)
        self._save_log(
            task_id=task.id,
            role=AgentRole.QA,
            raw=response.raw,
            parsed=parsed.data,
            status="SUCCESS" if parsed.success else "PARSE_ERROR",
            iteration=task.iteration_count,
        )
        return response.raw

    def _save_log(
        self, task_id: str, role: AgentRole, raw: str, parsed: dict, status: str, iteration: int
    ) -> None:
        """Save a log entry to storage."""
        entry = LogEntry(
            task_id=task_id,
            iteration=iteration,
            role=role,
            raw_response=raw,
            parsed_response=parsed,
            status=status,
        )
        self.storage.save_log(entry)

    def _generate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate final run summary."""
        total = len(results)
        done = sum(1 for r in results if r.get("status") == TaskStatus.DONE.value)
        blocked = sum(1 for r in results if r.get("status") == TaskStatus.BLOCKED.value)
        return {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_tasks": total,
            "tasks_done": done,
            "tasks_blocked": blocked,
            "success_rate": round(done / total, 2) if total > 0 else 0.0,
            "task_results": results,
        }
