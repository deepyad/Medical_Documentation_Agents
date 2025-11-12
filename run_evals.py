"""Run LangSmith evaluations.

This CLI launches `FormlyEvaluator`, which exercises the agent in evaluation
mode against mock API/database snapshots. All required scenarios and suites are
defined inside the evaluator/configuration, so no additional input is needed at
runtime—just ensure the necessary environment variables (e.g., API keys,
LangSmith credentials) are set before execution.
"""
from src.evals import FormlyEvaluator
from src.config import settings


def main():
    """Run evaluations."""
    print("Starting Formly agent evaluations...")
    
    evaluator = FormlyEvaluator()
    
    # Run evaluation
    results = evaluator.run_evaluation()
    
    print("\n=== Evaluation Results ===")
    print(f"Total runs: {results.get('total_runs', 0)}")
    print(f"Results: {results}")


if __name__ == "__main__":
    main()


