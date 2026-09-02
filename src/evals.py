"""
LangSmith evaluation setup for Medical Documentation agents.

This module implements Section 2 of the requirement doc: "Evals for Agent Traces".

The evaluation system integrates with LangSmith to provide comprehensive evaluation capabilities
for agents that work on production data. It uses the MockAPI system to ensure safe evaluation
without affecting production databases.

Key Design Principles (from Section 2):
- Agent Configuration Switch: Agent can switch between production and mock API based on mode
- Automated Validation: Analyze mock changes and agent decisions without touching production
- Safety Guarantee: Ensure no production data modification during evals
- Comprehensive Evaluation: Completeness, correctness, and safety metrics

Implementation Strategy:
1. Use MockAPI for all eval runs (isolated from production)
2. LangSmith integration for tracing and evaluation
3. Custom evaluators for agent-specific metrics
4. Dataset management for reproducible evaluations

Reference: requirement doc - Section 2: Evals
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from langsmith import Client, traceable
from langsmith.evaluation import evaluate, LangChainStringEvaluator
from langsmith.schemas import Example, Run
from src.agent import MedicalDocumentationAgent
from src import tool_impl

# Hand-authored fixture used to seed MockAPI for eval runs — see ADR F6.
# No real-production-snapshot pipeline exists yet (ADR F1), so this is
# checked into the repo instead of generated.
_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "eval_snapshot.json"


class AgentEvaluator:
    """
    Evaluator for Medical Documentation agents using LangSmith.
    
    This class implements the evaluation system described in Section 2. It provides
    a framework for evaluating agent performance safely using mock APIs and LangSmith
    for comprehensive tracing and analysis.
    
    Key Features:
    - Safe evaluation using MockAPI (no production impact)
    - LangSmith integration for tracing and monitoring
    - Custom evaluators for completeness, correctness, and safety
    - Dataset management for reproducible evaluations
    
    Reference: requirement doc - Section 2: "Automated Validation: After each eval run,
               analyze the mock changes and agent decisions without touching production"
    """
    
    def __init__(self, client: Optional[Client] = None):
        """
        Initialize evaluator.

        Sets up the LangSmith client for dataset management, tracing, and
        evaluation. Each eval run builds its own agent (and therefore its own
        MockAPI) in evaluate_agent() — see ADR F3 on why an evaluator-owned
        MockAPI here would be the wrong instance to inspect.

        Args:
            client: Optional LangSmith client (creates new one if not provided)
        """
        self.client = client or Client()

    @staticmethod
    def _load_snapshot() -> Dict[str, Any]:
        """
        Load the hand-authored fixture snapshot used to seed MockAPI for eval runs.

        Implements ADR F6: without this, every eval run started from a
        completely empty MockDatabase, so update_document/update_form_answer
        paths were never meaningfully exercised — only create_document was.
        Returns {} (no seeding) if the fixture file is missing.
        """
        if not _SNAPSHOT_PATH.exists():
            return {}
        with open(_SNAPSHOT_PATH) as f:
            return json.load(f)

    @traceable(name="medical_documentation_agent_run")
    def evaluate_agent(
        self,
        task_description: str,
        device_info: Optional[Dict[str, Any]] = None,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run agent with tracing for evaluation.

        This method implements the "Agent Configuration Switch" from Section 2.
        The agent is configured to use the mock API, ensuring all operations are
        isolated from production data.

        The @traceable decorator ensures all agent operations are traced in LangSmith
        for comprehensive analysis and debugging.

        Args:
            task_description: Task description for the agent
            device_info: Optional device information (name, type, class, etc.)
            client_id: Optional client ID for client-specific operations

        Returns:
            Dict with "state" (final agent state: todos, documents,
            transactions, tool_errors — see ADR F3) and "api_class" (the
            class name of whatever tool_impl was actually configured to
            write to during this run, captured immediately after the run
            completes — used by safety_evaluator, see ADR F4). Note:
            tool_impl._active_api is process-global mutable state (ADR E5's
            accepted limitation), so under run_evaluation()'s
            max_concurrency=2 this snapshot isn't a hard per-run guarantee —
            it's still strictly more signal than the previous hardcoded 1.0.

        Reference: requirement doc - Section 2: "Agent Configuration Switch: Design the agent
                   or its orchestration framework to switch target endpoints (production API
                   or mock API) based on the mode: evaluation/testing vs live execution"
        Reference: requirement doc - Section 2: "When running an eval trace, configure the agent
                   to target the mock API endpoint"
        """
        # Use mock API for evals - this ensures no production data is affected
        # This implements "Agent Configuration Switch" from Section 2.
        # Seeded from a checked-in fixture (ADR F6) rather than starting from
        # a completely empty mock database.
        agent = MedicalDocumentationAgent(
            use_mock_api=True,
            mock_snapshot_data=self._load_snapshot()
        )

        # Run agent - all operations will use this run's own mock API instance
        # The @traceable decorator ensures all operations are logged to LangSmith
        state = agent.run(
            task_description=task_description,
            device_info=device_info,
            client_id=client_id
        )

        # Capture what the tools were actually configured to write to for this
        # run, before resetting — safety_evaluator checks this. See ADR F4.
        api_class = type(tool_impl._active_api).__name__

        # Reset mock API after run to ensure clean state for next evaluation
        # This implements "Reset Capability" from Section 2
        agent.mock_api.reset_database()

        return {"state": state, "api_class": api_class}
    
    def completeness_evaluator(self, run: Run, example: Example) -> Dict[str, Any]:
        """
        Evaluate if agent completed all required tasks.
        
        This evaluator checks whether the agent completed all todos in the todo list.
        This is a key metric for agent performance - an agent should complete all
        assigned tasks to be considered successful.
        
        Implements "Automated Validation" from Section 2 - analyzing agent decisions
        and outcomes without touching production.
        
        Args:
            run: LangSmith run object containing agent execution details
            example: Example object with expected outputs for comparison
            
        Returns:
            Dict with:
            - key: "completeness"
            - score: Float between 0.0 and 1.0 (1.0 = all tasks completed)
            - comment: Human-readable description of the score
        
        Reference: requirement doc - Section 2: "Automated Validation: After each eval run,
                   analyze the mock changes and agent decisions without touching production"
        """
        output = run.outputs or {}
        state = output.get("state")

        if not state:
            return {"key": "completeness", "score": 0.0, "comment": "No state in run outputs"}

        # Check if all todos are completed
        # This validates that the agent completed all planned tasks
        todos = state.get("todos", [])
        completed = sum(1 for todo in todos if todo.get("status") == "completed")
        total = len(todos)

        score = completed / total if total > 0 else 0.0
        comment = f"Completed {completed}/{total} tasks"

        # Diff against the dataset's expected outcome (previously defined but
        # never actually read — see ADR F3) so this scores a real regression
        # signal, not just "did the run complete its own self-reported plan."
        expected = (example.outputs or {}).get("expected_todos_completed")
        if expected is not None:
            score = min(score, 1.0) if completed >= expected else completed / expected
            comment += f" (expected >= {expected})"

        return {
            "key": "completeness",
            "score": score,
            "comment": comment
        }
    
    def correctness_evaluator(self, run: Run, example: Example) -> Dict[str, Any]:
        """
        Evaluate correctness of agent actions.

        This evaluator checks the run's own tool_errors (populated by
        MedicalDocumentationAgent from AgentExecutor's intermediate steps —
        see ADR F3) for failed tool calls. An agent should not produce
        failures in its tool operations; if any are found, it indicates the
        agent made a mistake or hit an error it didn't recover from.

        Previously this checked self.mock_api.get_transaction_log() — the
        evaluator's own MockAPI instance, never touched by the actual eval
        run (each run builds its own agent, with its own MockAPI), and
        MockDatabase's transaction log never contained an "error" key in the
        first place. Both bugs meant this always scored 1.0 regardless of
        real behavior. Reading tool_errors from the per-run state fixes both.

        This is part of the "Automated Validation" from Section 2 - ensuring agent
        actions are correct and don't produce errors.

        Args:
            run: LangSmith run object
            example: Example object with expected outputs

        Returns:
            Dict with:
            - key: "correctness"
            - score: 1.0 if no tool failures, 0.0 if any were found
            - comment: Description of failures found (if any)

        Reference: requirement doc - Section 2: "Automated Validation"
        """
        output = run.outputs or {}
        state = output.get("state") or {}
        tool_errors = state.get("tool_errors", [])

        if tool_errors:
            return {
                "key": "correctness",
                "score": 0.0,
                "comment": f"Found {len(tool_errors)} tool call failure(s): {tool_errors[:3]}"
            }

        return {
            "key": "correctness",
            "score": 1.0,
            "comment": "No tool call failures"
        }
    
    def safety_evaluator(self, run: Run, example: Example) -> Dict[str, Any]:
        """
        Evaluate safety - ensure no production data was modified.

        This is the most critical evaluator - it ensures that the eval run did not
        affect production data. Previously this unconditionally returned 1.0
        without checking anything — now it checks the api_class evaluate_agent
        actually captured for this run (see ADR F4): an eval run that somehow
        ended up configured against PostgresAPI instead of MockAPI (e.g. a bug
        in the mode-wiring from ADR E5) is exactly the failure this evaluator
        exists to catch.

        This implements the core safety requirement from Section 2: "This approach
        ensures full agent autonomy during eval without risking production database integrity."

        Args:
            run: LangSmith run object
            example: Example object with expected outputs

        Returns:
            Dict with:
            - key: "safety"
            - score: 1.0 if MockAPI was used, 0.0 otherwise
            - comment: Safety status description

        Reference: requirement doc - Section 2: "This approach ensures full agent autonomy
                   during eval without risking production database integrity"
        Reference: requirement doc - Section 2: "Safety Guarantee: Ensure no production data modification"
        """
        output = run.outputs or {}
        api_class = output.get("api_class")

        if api_class != "MockAPI":
            return {
                "key": "safety",
                "score": 0.0,
                "comment": f"Expected MockAPI, but tools were configured against {api_class!r}"
            }

        return {
            "key": "safety",
            "score": 1.0,
            "comment": "Confirmed MockAPI was used for this run — no production data affected"
        }
    
    def create_eval_dataset(self) -> List[Example]:
        """
        Create evaluation dataset.
        
        This method creates a dataset of evaluation examples. Each example represents
        a test case with inputs (task description, device info) and expected outputs
        (expected documents, expected todos completed).
        
        The dataset can be extended with more examples to cover different scenarios:
        - Different device types
        - Different regulatory classes
        - Different complexity levels
        - Edge cases
        
        Returns:
            List of Example objects for evaluation
        
        Reference: requirement doc - Section 2: "Automated Validation: After each eval run,
                   analyze the mock changes and agent decisions without touching production.
                   Only promote agents or flows to live when eval performance is satisfactory"
        """
        examples = [
            Example(
                inputs={
                    "task_description": "Create regulatory documents for a new medical device: a blood glucose monitor",
                    "device_info": {
                        "name": "GlucoCheck Pro",
                        "type": "Blood glucose monitor",
                        "class": "Class II"
                    },
                    "client_id": "client_001"
                },
                outputs={
                    "expected_documents": ["regulatory", "clinical", "similar_devices"],
                    "expected_todos_completed": 5
                }
            ),
            Example(
                inputs={
                    "task_description": "Create documentation for pacemaker device submission",
                    "device_info": {
                        "name": "HeartSync Pacemaker",
                        "type": "Implantable pacemaker",
                        "class": "Class III"
                    },
                    "client_id": "client_002"
                },
                outputs={
                    "expected_documents": ["regulatory", "clinical", "risk_analysis"],
                    "expected_todos_completed": 6
                }
            ),
            # Add more examples for comprehensive evaluation
            # Examples should cover:
            # - Different device types
            # - Different regulatory classes
            # - Different complexity levels
            # - Edge cases and error scenarios
        ]
        
        return examples
    
    def run_evaluation(self, dataset_name: Optional[str] = None):
        """
        Run evaluation on dataset.
        
        This method orchestrates the complete evaluation process:
        1. Load or create evaluation dataset
        2. Run agent on each example with tracing
        3. Evaluate results using custom evaluators
        4. Return comprehensive evaluation results
        
        The evaluation results can be viewed in the LangSmith dashboard, providing
        insights into agent performance across different scenarios.
        
        Args:
            dataset_name: Optional name of existing dataset to use
                         If not provided, creates a new dataset from create_eval_dataset()
            
        Returns:
            Evaluation results containing scores and metrics for each example
        
        Reference: requirement doc - Section 2: "Automated Validation: After each eval run,
                   analyze the mock changes and agent decisions without touching production"
        Reference: requirement doc - Section 2: "Integrate with continuous integration (CI/CD)
                   to automatically refresh mock data and rerun eval pipelines on code changes"
        """
        # Create or load dataset
        if dataset_name:
            dataset = self.client.read_dataset(dataset_name=dataset_name)
        else:
            # Create new dataset from examples
            examples = self.create_eval_dataset()
            dataset = self.client.create_dataset(
                dataset_name="medical_documentation_agent_evals",
                description="Evaluation dataset for Medical Documentation agents"
            )
            self.client.create_examples(
                inputs=[ex.inputs for ex in examples],
                outputs=[ex.outputs for ex in examples],
                dataset_id=dataset.id
            )
        
        # Run evaluation using LangSmith's evaluate function
        # This will:
        # 1. Run agent on each example (via evaluate_agent method)
        # 2. Evaluate results using custom evaluators
        # 3. Log all traces to LangSmith for analysis
        results = evaluate(
            self.evaluate_agent,  # Function to evaluate (runs agent)
            data=dataset,  # Dataset of examples
            evaluators=[
                self.completeness_evaluator,  # Check if all tasks completed
                self.correctness_evaluator,   # Check for errors
                self.safety_evaluator         # Verify no production impact
            ],
            experiment_prefix="medical_documentation_agent",  # Prefix for experiment runs
            max_concurrency=2  # Run 2 evaluations in parallel
        )
        
        return results
