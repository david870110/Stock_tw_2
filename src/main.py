"""Main entry point for the AutoPrograming framework."""
import argparse
import json
from src.orchestrator.engine import OrchestratorEngine, OrchestratorConfig
from src.agents.manager import MockManagerAgentClient
from src.agents.planner import MockPlannerAgentClient
from src.agents.coder import MockCoderAgentClient
from src.agents.qa import MockQAAgentClient


def main():
    parser = argparse.ArgumentParser(description="AutoPrograming - Multi-Agent Coding Automation Framework")
    parser.add_argument("requirement", type=str, help="User requirement to implement")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--storage-path", type=str, default="runs")
    args = parser.parse_args()

    config = OrchestratorConfig(
        max_iterations=args.max_iterations,
        storage_path=args.storage_path,
    )

    engine = OrchestratorEngine(
        config=config,
        manager_client=MockManagerAgentClient(),
        planner_client=MockPlannerAgentClient(),
        coder_client=MockCoderAgentClient(),
        qa_client=MockQAAgentClient(),
    )

    summary = engine.run(args.requirement)
    print("\n=== Final Summary ===")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
