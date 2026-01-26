"""Main script to run the Medical Documentation agent.

This entry point executes a single end-to-end workflow using the production
API path (`use_mock_api=False`). It ships with a hard-coded sample task and
device payload so you can run it without providing any input. Modify the
`task_description` and `device_info` blocks—or extend the script with CLI
arguments—if you need to exercise different scenarios.
"""
import asyncio
from src.agent import MedicalDocumentationAgent
from src.config import settings


def main():
    """Run the agent with a sample task."""
    agent = MedicalDocumentationAgent(use_mock_api=False)  # Set to True for evals
    
    task_description = """
    Create regulatory documents for a new medical device submission.
    The device is a blood glucose monitoring system with continuous monitoring capabilities.
    Create the following documents:
    1. Regulatory requirements document
    2. Clinical data summary
    3. Similar devices analysis
    4. Risk analysis document
    """
    
    device_info = {
        "name": "GlucoCheck Pro",
        "type": "Blood glucose monitor",
        "class": "Class II",
        "intended_use": "Continuous glucose monitoring for diabetes management"
    }
    
    print("Starting agent workflow...")
    state = agent.run(
        task_description=task_description,
        device_info=device_info,
        client_id="client_001"
    )
    
    print("\n=== Agent Completed ===")
    print(f"Todos completed: {sum(1 for t in state.todos if t.status.value == 'completed')}/{len(state.todos)}")
    print(f"Documents created: {len(state.documents)}")
    print(f"Transactions: {len(state.transactions)}")


if __name__ == "__main__":
    main()


