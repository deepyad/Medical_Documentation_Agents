"""
Main LangGraph agent for multi-document creation.

This module implements the core agent orchestration that integrates all sections of the
requirement doc. The agent uses LangGraph to create a multi-phase workflow for
generating regulatory documents.

Integration of All Sections:
- Section 1 (Rollbacks): All destructive actions use rollback tracking
- Section 2 (Evals): Agent can run in eval mode with MockAPI
- Section 3 (RAG): Uses hybrid retrieval for finding similar devices
- Section 4 (Knowledge): Retrieves global and client-specific knowledge
- Section 5 (Context): Manages context with segmentation and compression

Agent Workflow:
1. Plan Phase: Create hierarchical todo list
2. Research Phase: Gather information (RAG + Knowledge retrieval)
3. Create Documents Phase: Generate documents (with rollback tracking)
4. Review Phase: Review and revise documents
5. Context Compression: Compress context when limits are reached

Key Features:
- Multi-document creation (10+ documents)
- Context segmentation by topic
- Automatic context compression
- Transaction tracking for all actions
- Support for both production and eval modes

Reference: requirement doc - Sections 1-5 (Integrated)
"""
from typing import Dict, Any, List, Optional, Literal
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_openai_tools_agent
from src.config import settings
from src.models import AgentState, TodoItem, TaskStatus, DocumentType
from src.tools import AGENT_TOOLS
from src.context_manager import ContextManager
from src.mock_api import MockAPI
import json


class MedicalDocumentationAgent:
    """
    Main agent for creating regulatory documents.
    
    This agent integrates all components from Sections 1-5 of the requirement doc:
    - Uses rollback system (Section 1) for all destructive actions
    - Supports eval mode with MockAPI (Section 2)
    - Uses RAG pipeline (Section 3) for finding similar devices
    - Retrieves knowledge (Section 4) for context-aware responses
    - Manages context (Section 5) to prevent drift and pollution
    
    The agent uses LangGraph to orchestrate a multi-phase workflow for creating
    multiple regulatory documents while maintaining context and tracking all actions.
    
    Reference: requirement doc - Section 5: "You have to build an agent that gets a task
               and then gets to work creating 10+ documents for a specific device which
               involves researching regulatory requirements, clinical data, similar devices etc."
    """
    
    def __init__(self, use_mock_api: bool = False):
        """
        Initialize Medical Documentation agent.
        
        Args:
            use_mock_api: Whether to use mock API (for evals)
                         True = Use MockAPI (Section 2) for safe evaluation
                         False = Use production API (Section 1 rollback system)
        
        Reference: requirement doc - Section 2: "Agent Configuration Switch: Design the agent
                   or its orchestration framework to switch target endpoints (production API
                   or mock API) based on the mode: evaluation/testing vs live execution"
        """
        self.llm = ChatOpenAI(
            model="gpt-4-turbo-preview",
            temperature=0,
            api_key=settings.openai_api_key
        )
        
        self.use_mock_api = use_mock_api
        self.mock_api = MockAPI() if use_mock_api else None
        
        self.context_manager = ContextManager()
        
        # Create agent with tools
        self.agent_executor = self._create_agent_executor()
        
        # Build LangGraph workflow
        self.workflow = self._build_workflow()
    
    def _create_agent_executor(self) -> AgentExecutor:
        """Create agent executor with tools."""
        system_prompt = """You are a regulatory documentation agent specialized in creating 
medical device regulatory documents. Your task is to:

1. Research regulatory requirements and similar devices
2. Gather clinical data and knowledge
3. Create comprehensive documents for regulatory submissions

You have access to tools for:
- Searching similar devices from FDA 510(k) database
- Retrieving knowledge (global and client-specific)
- Creating and updating documents
- Updating form answers
- Rolling back transactions if needed

Always track your progress using the todo list and update it as you complete tasks.
When creating documents, ensure they are comprehensive and based on retrieved information."""
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
        
        agent = create_openai_tools_agent(
            self.llm,
            AGENT_TOOLS,
            prompt=prompt
        )
        
        return AgentExecutor(
            agent=agent,
            tools=AGENT_TOOLS,
            verbose=True,
            handle_parsing_errors=True
        )
    
    def _build_workflow(self) -> StateGraph:
        """Build LangGraph workflow."""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("plan", self._plan_phase)
        workflow.add_node("research", self._research_phase)
        workflow.add_node("create_documents", self._create_documents_phase)
        workflow.add_node("review", self._review_phase)
        workflow.add_node("compress_context", self._compress_context_node)
        
        # Add edges
        workflow.set_entry_point("plan")
        workflow.add_edge("plan", "research")
        workflow.add_conditional_edges(
            "research",
            self._should_compress,
            {
                "compress": "compress_context",
                "continue": "create_documents"
            }
        )
        workflow.add_edge("compress_context", "create_documents")
        workflow.add_conditional_edges(
            "create_documents",
            self._check_completion,
            {
                "continue": "review",
                "done": END
            }
        )
        workflow.add_conditional_edges(
            "review",
            self._needs_revision,
            {
                "revise": "create_documents",
                "done": END
            }
        )
        
        return workflow.compile()
    
    def _plan_phase(self, state: AgentState) -> Dict[str, Any]:
        """
        Planning phase - create todo list.
        
        This implements the "Hierarchical To-Do List & Checkpointing" from Section 5.
        Creates a detailed todo list breaking down the work into research, document creation,
        and review tasks.
        
        Reference: requirement doc - Section 5: "Expand the todo list into a hierarchical action
                   planner with explicit checkpoints after each major subtask or document draft"
        """
        if state.todos:
            # Already planned
            return {}
        
        planning_prompt = f"""Based on this task: {state.task_description}

Create a detailed todo list for creating all required documents. Break down the work into:
1. Research tasks (regulatory requirements, similar devices, clinical data)
2. Document creation tasks (one per document type)
3. Review and revision tasks

Return a JSON list of todos with descriptions and dependencies."""
        
        response = self.llm.invoke([
            SystemMessage(content="You are a planning agent. Create detailed todo lists."),
            HumanMessage(content=planning_prompt)
        ])
        
        # Parse todos from response
        try:
            todos_data = json.loads(response.content)
            todos = [
                TodoItem(
                    id=f"todo_{i}",
                    description=item.get("description", ""),
                    dependencies=item.get("dependencies", [])
                )
                for i, item in enumerate(todos_data)
            ]
        except:
            # Fallback: create basic todos
            todos = [
                TodoItem(id="todo_0", description="Research regulatory requirements"),
                TodoItem(id="todo_1", description="Find similar devices"),
                TodoItem(id="todo_2", description="Gather clinical data"),
                TodoItem(id="todo_3", description="Create regulatory documents"),
                TodoItem(id="todo_4", description="Review and revise documents")
            ]
        
        return {"todos": todos}
    
    def _research_phase(self, state: AgentState) -> Dict[str, Any]:
        """
        Research phase - gather information.
        
        This phase integrates Section 3 (RAG) and Section 4 (Knowledge Retrieval):
        - Uses RAG pipeline to find similar devices (Section 3)
        - Retrieves global and client-specific knowledge (Section 4)
        - Stores research results in context segments (Section 5)
        
        Reference: requirement doc - Section 3: "Agent creates query string from device information"
        Reference: requirement doc - Section 4: "Agent queries vector DB with embedded contextual
                   query vector. Apply metadata filters to scope retrieval by client/global as needed"
        """
        # Find next research todo
        research_todos = [
            todo for todo in state.todos
            if todo.status == TaskStatus.PENDING and "research" in todo.description.lower()
        ]
        
        if not research_todos:
            return {}
        
        current_todo = research_todos[0]
        
        # Retrieve relevant knowledge
        query = f"{state.task_description} {current_todo.description}"
        
        # Use agent executor to perform research
        research_input = f"""Research information for: {current_todo.description}
        
Task context: {state.task_description}
Device info: {state.device_info or 'Not provided'}

Use the available tools to:
1. Search for similar devices
2. Retrieve relevant knowledge (global and client-specific)
3. Gather all necessary information"""
        
        result = self.agent_executor.invoke({
            "input": research_input,
            "chat_history": state.messages
        })
        
        # Update todo
        current_todo.status = TaskStatus.COMPLETED
        current_todo.result = {"research_output": result.get("output", "")}
        
        # Add to context
        self.context_manager.add_to_segment(
            "research",
            result.get("output", ""),
            relevance=1.0
        )
        
        return {
            "todos": state.todos,
            "messages": state.messages + [
                {"role": "user", "content": research_input},
                {"role": "assistant", "content": result.get("output", "")}
            ]
        }
    
    def _create_documents_phase(self, state: AgentState) -> Dict[str, Any]:
        """Create documents phase."""
        # Find document creation todos
        doc_todos = [
            todo for todo in state.todos
            if todo.status == TaskStatus.PENDING and "document" in todo.description.lower()
        ]
        
        if not doc_todos:
            return {}
        
        current_todo = doc_todos[0]
        
        # Get context
        context = self.context_manager.get_context_string(
            max_tokens=2000,
            current_focus="research"
        )
        
        # Create document
        creation_input = f"""Create a document based on:
Todo: {current_todo.description}
Context: {context}

Use the create_document tool to create the document with all relevant information."""
        
        result = self.agent_executor.invoke({
            "input": creation_input,
            "chat_history": state.messages
        })
        
        # Update todo
        current_todo.status = TaskStatus.COMPLETED
        current_todo.result = result
        
        return {
            "todos": state.todos,
            "messages": state.messages + [
                {"role": "user", "content": creation_input},
                {"role": "assistant", "content": result.get("output", "")}
            ]
        }
    
    def _review_phase(self, state: AgentState) -> Dict[str, Any]:
        """Review phase."""
        review_prompt = """Review all created documents and determine if any revisions are needed.
        
Check for:
- Completeness
- Accuracy
- Consistency
- Regulatory compliance"""
        
        result = self.agent_executor.invoke({
            "input": review_prompt,
            "chat_history": state.messages
        })
        
        return {
            "messages": state.messages + [
                {"role": "user", "content": review_prompt},
                {"role": "assistant", "content": result.get("output", "")}
            ]
        }
    
    def _compress_context_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Compress context when needed.
        
        This implements "Dynamic Context Compression with Relevance Scoring" from Section 5.
        When context reaches 60% of the window limit, compress segments based on relevance.
        
        Reference: requirement doc - Section 5: "Context compression after 60% of context window is used"
        Reference: requirement doc - Section 5: "Use relevance-based compression: Only compress/remove
                   least relevant or redundant parts"
        """
        # Build context segments from state
        for segment_name, content_list in state.context_segments.items():
            self.context_manager.add_to_segment(segment_name, "\n".join(content_list))
        
        # Compress
        compressed_state = self.context_manager.compress_context(state)
        
        return {"context_segments": compressed_state.context_segments}
    
    def _should_compress(self, state: AgentState) -> Literal["compress", "continue"]:
        """Determine if context compression is needed."""
        total_tokens = sum(
            len(self.context_manager.encoding.encode(content))
            for segment_content in state.context_segments.values()
            for content in segment_content
        )
        
        if self.context_manager.should_compress(total_tokens):
            return "compress"
        return "continue"
    
    def _check_completion(self, state: AgentState) -> Literal["continue", "done"]:
        """Check if all todos are completed."""
        pending_todos = [
            todo for todo in state.todos
            if todo.status == TaskStatus.PENDING
        ]
        
        if pending_todos:
            return "continue"
        return "done"
    
    def _needs_revision(self, state: AgentState) -> Literal["revise", "done"]:
        """Check if documents need revision."""
        # Simple heuristic: check last message for revision keywords
        if state.messages:
            last_message = state.messages[-1].get("content", "").lower()
            if any(keyword in last_message for keyword in ["revise", "update", "fix", "change"]):
                return "revise"
        return "done"
    
    def run(self, task_description: str, device_info: Optional[Dict[str, Any]] = None, 
            client_id: Optional[str] = None) -> AgentState:
        """
        Run the agent workflow.
        
        Args:
            task_description: Task description
            device_info: Optional device information
            client_id: Optional client ID
            
        Returns:
            Final agent state
        """
        initial_state = AgentState(
            task_description=task_description,
            device_info=device_info,
            client_id=client_id
        )
        
        # Run workflow
        final_state = self.workflow.invoke(initial_state)
        
        return final_state

