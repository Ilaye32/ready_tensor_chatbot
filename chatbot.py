from langsmith import traceable
import os
from typing import TypedDict, Annotated, Literal, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
import operator
import sys
import json
from tavily import TavilyClient
import re
from datetime import datetime
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import chainlit as cl

# Load environment variables
load_dotenv()

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging() -> logging.Logger:
    """
    Configure logging with both file and console handlers
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("ready_tensor_chatbot")
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except OSError as e:
            log_dir = "."
            logger.warning(f"Could not create logs directory: {e}. Using current directory.")
    
    # File handler with rotation
    log_file = os.path.join(log_dir, f"chatbot_{datetime.now().strftime('%Y%m%d')}.log")
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create file handler: {e}. Continuing with console only.")
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

# Initialize logger
logger = setup_logging()

# ============================================================================
# ENVIRONMENT VALIDATION
# ============================================================================

def validate_environment() -> Dict[str, bool]:
    """
    Validate required environment variables
    
    Returns:
        Dictionary with validation status for each required key
    """
    required_keys = {
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY"),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY")
    }
    
    validation_status = {}
    for key, value in required_keys.items():
        is_valid = bool(value and value.strip())
        validation_status[key] = is_valid
        
        if not is_valid:
            logger.error(f"Missing or empty environment variable: {key}")
        else:
            logger.info(f"Environment variable validated: {key}")
    
    return validation_status

# ============================================================================
# TOOLS DEFINITION WITH ENHANCED ERROR HANDLING
# ============================================================================

@tool
def web_search_tool(query: str) -> dict:
    """
    Search the web for real-time information using Tavily API.
    Returns properly formatted JSON results.
    
    Args:
        query: Search query string
    
    Returns:
        Dictionary with search results and metadata
    """
    logger.info(f"Web search initiated: {query[:100]}")
    
    try:
        # Get API key from environment
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key or not tavily_api_key.strip():
            error_msg = "TAVILY_API_KEY environment variable not set or empty"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "results": []
            }
        
        # Initialize Tavily client
        tavily = TavilyClient(api_key=tavily_api_key)
        
        # Perform web search with error handling
        search_results = tavily.search(
            query=query, 
            max_results=3,
            include_answer=True,
            include_raw_content=False
        )
        
        # Parse and validate results
        if not search_results:
            logger.warning(f"Empty response from Tavily for query: {query}")
            return {
                "status": "success",
                "message": "No results found",
                "query": query,
                "results": []
            }
        
        # Extract results with proper error handling
        formatted_results = []
        raw_results = search_results.get("results", [])
        
        for idx, item in enumerate(raw_results):
            try:
                formatted_result = {
                    "title": item.get("title", "No title available"),
                    "url": item.get("url", ""),
                    "content": item.get("content", "No content available"),
                    "score": item.get("score", 0.0),
                    "published_date": item.get("published_date", "Unknown")
                }
                formatted_results.append(formatted_result)
            except Exception as e:
                logger.warning(f"Error processing result {idx}: {str(e)}")
                continue
        
        # Get answer if available
        answer = search_results.get("answer", "")
        
        result = {
            "status": "success",
            "query": query,
            "answer": answer,
            "results": formatted_results,
            "result_count": len(formatted_results)
        }
        
        logger.info(f"Web search successful: {len(formatted_results)} results found")
        return result
        
    except ValueError as e:
        error_msg = f"Invalid API key or configuration: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": error_msg,
            "query": query,
            "results": []
        }
    except ConnectionError as e:
        error_msg = f"Network connection error: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "message": f"{error_msg}. Please check your internet connection.",
            "query": query,
            "results": []
        }
    except Exception as e:
        error_msg = f"Web search error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "query": query,
            "results": []
        }


@tool
def document_retrieval_tool(topic: str, module: str = "all") -> dict:
    """
    Retrieve specific documentation about course topics, modules, or concepts.
    
    Args:
        topic: Topic to retrieve documentation for
        module: Specific module number or "all" for all modules
    
    Returns:
        Dictionary with documentation results
    """
    logger.info(f"Document retrieval for topic: {topic}, module: {module}")
    
    try:
        documents = {
            "rag": {
                "module": "1",
                "title": "RAG (Retrieval-Augmented Generation)",
                "content": """Build systems that combine LLM generation with external knowledge retrieval. Use vector databases (Qdrant, FAISS) to store and retrieve relevant documents. Implement semantic search using embeddings. Create context-aware responses by augmenting prompts with retrieved information. Learn chunking strategies for optimal retrieval.

Project: Build a LangGraph-powered assistant that answers questions using real documentation with ReAct-based reasoning."""
            },
            "langgraph": {
                "module": "2",
                "title": "LangGraph (Multi-Agent Systems)",
                "content": """Design complex agent workflows with state management. Create multi-agent systems with coordination patterns. Implement human-in-the-loop interactions. Build conditional routing between agents. Manage agent memory and conversation state. Use graph-based orchestration for complex tasks.

LangGraph enables you to build stateful, multi-step applications with LLMs. It's particularly useful for creating agentic systems that need to maintain context and coordinate between multiple specialized agents."""
            },
            "vector_databases": {
                "module": "1",
                "title": "Vector Databases (Qdrant, FAISS)",
                "content": """Store embeddings for semantic search. Qdrant: Production-ready vector database with filtering. FAISS: Facebook's library for efficient similarity search. Learn embedding strategies and indexing. Implement hybrid search (keyword + semantic). Optimize for retrieval speed and accuracy.

Used extensively in RAG systems for efficient document retrieval."""
            },
            "security": {
                "module": "3",
                "title": "Security & Guardrails",
                "content": """OWASP Top 10 for LLM Applications: 1. Prompt Injection, 2. Insecure Output Handling, 3. Training Data Poisoning, 4. Model Denial of Service, 5. Supply Chain Vulnerabilities, 6. Sensitive Information Disclosure, 7. Insecure Plugin Design, 8. Excessive Agency, 9. Overreliance, 10. Model Theft.

Implement input validation and sanitization. Add content filtering and safety layers. Monitor for adversarial attacks. Use guardrails to prevent harmful outputs."""
            },
            "deployment": {
                "module": "3",
                "title": "Deployment Strategies",
                "content": """FastAPI for lightweight, production-ready APIs. Containerization with Docker. Cloud deployment (AWS, GCP, Azure). Monitoring and observability with LangSmith. Load testing and performance optimization. CI/CD pipelines for agentic systems. Cost optimization strategies.

Project: Transform your multi-agent system into a production-ready application with full testing suite and deployment configuration."""
            },
            "testing": {
                "module": "3",
                "title": "Testing Agentic AI Systems",
                "content": """Unit testing with pytest. Integration testing for multi-agent workflows. Evaluation frameworks (Giskard). Testing for safety and alignment. Performance benchmarking. Regression testing for LLM outputs. A/B testing for prompt variations.

Learn to build comprehensive test suites that ensure your agentic systems are reliable, safe, and performant."""
            }
        }
        
        topic_lower = topic.lower().replace(" ", "_")
        
        # Find matching documents
        matches = []
        for key, doc in documents.items():
            if topic_lower in key or key in topic_lower:
                if module == "all" or doc["module"] == str(module):
                    matches.append({
                        "topic": key,
                        "module": doc["module"],
                        "title": doc["title"],
                        "content": doc["content"]
                    })
        
        if matches:
            logger.info(f"Found {len(matches)} document(s) for topic: {topic}")
            return {
                "status": "success",
                "topic": topic,
                "module": module,
                "documents": matches,
                "count": len(matches)
            }
        else:
            logger.warning(f"No documentation found for topic: {topic}")
            return {
                "status": "not_found",
                "topic": topic,
                "message": f"No specific documentation found for '{topic}'",
                "available_topics": ["RAG", "LangGraph", "vector_databases", "security", "deployment", "testing"],
                "documents": []
            }
    
    except Exception as e:
        error_msg = f"Document retrieval error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "message": error_msg,
            "topic": topic,
            "documents": []
        }


@tool
def code_executor_tool(code: str, language: str = "python") -> dict:
    """
    Execute simple Python code snippets to help users test concepts.
    
    Args:
        code: Python code to execute
        language: Programming language (currently only Python supported)
    
    Returns:
        Dictionary with execution results
    """
    logger.info(f"Code execution requested: {len(code)} characters")
    
    try:
        if language.lower() != "python":
            logger.warning(f"Unsupported language requested: {language}")
            return {
                "status": "error",
                "message": f"Currently only Python execution is supported. You requested: {language}",
                "output": ""
            }
        
        # Security check: block dangerous operations
        dangerous_patterns = [
            r'\bimport\s+os\b', r'\bimport\s+sys\b', r'\bimport\s+subprocess\b',
            r'\bopen\s*\(', r'\bexec\s*\(', r'\beval\s*\(',
            r'\b__import__\b', r'\bcompile\s*\(',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                logger.warning(f"Blocked unsafe code execution attempt")
                return {
                    "status": "blocked",
                    "message": "Security Error: This code contains potentially unsafe operations.",
                    "details": "Cannot execute code that imports os/sys/subprocess, uses open()/exec()/eval(), or accesses file system/network",
                    "output": ""
                }
        
        # Check for LangChain/LangGraph imports
        if 'langchain' in code.lower() or 'langgraph' in code.lower():
            logger.info("LangChain/LangGraph code detected")
            return {
                "status": "blocked",
                "message": "LangChain/LangGraph code detected",
                "details": "Cannot execute LangChain code directly (requires API keys). I can explain what it does instead.",
                "output": ""
            }
        
        # Execute safe code
        from io import StringIO
        
        safe_globals = {
            '__builtins__': {
                'print': print, 'len': len, 'range': range, 'str': str,
                'int': int, 'float': float, 'list': list, 'dict': dict,
                'set': set, 'tuple': tuple, 'bool': bool, 'sum': sum,
                'max': max, 'min': min, 'abs': abs, 'round': round,
                'sorted': sorted, 'enumerate': enumerate, 'zip': zip,
            }
        }
        
        # Capture output
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            exec(code, safe_globals)
            output = captured_output.getvalue()
            logger.info("Code executed successfully")
            
            return {
                "status": "success",
                "message": "Code executed successfully",
                "output": output if output else "(no output produced)",
                "code": code
            }
        
        finally:
            sys.stdout = old_stdout
            
    except SyntaxError as e:
        error_msg = f"Syntax error: {str(e)}"
        logger.warning(error_msg)
        return {
            "status": "error",
            "message": "Syntax Error",
            "details": str(e),
            "output": ""
        }
    except NameError as e:
        error_msg = f"Name error: {str(e)}"
        logger.warning(error_msg)
        return {
            "status": "error",
            "message": "Name Error",
            "details": str(e),
            "output": ""
        }
    except Exception as e:
        error_msg = f"Execution error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "message": "Execution Error",
            "details": str(e),
            "output": ""
        }


# ============================================================================
# KNOWLEDGE BASE
# ============================================================================

COURSE_KNOWLEDGE = {
    "program_overview": {
        "name": "Agentic AI Developer Certification Program",
        "duration": "12 weeks",
        "cost": "Free",
        "provider": "Ready Tensor",
        "structure": "3 modules + 1 optional advanced module",
        "certification": "Complete all 3 projects to earn full certification",
        "micro_certs": "Earn micro-certificates for each module completed"
    },
    "modules": {
        "module_1": {
            "name": "Foundations of Agentic AI",
            "weeks": "1-4",
            "topics": [
                "Core concepts of agentic AI",
                "LangChain framework basics",
                "Prompt engineering and reasoning techniques",
                "LLM calls and multi-turn conversations",
                "Building RAG (Retrieval-Augmented Generation) systems",
                "Vector databases (Qdrant, FAISS)"
            ],
            "project": "LangGraph-powered assistant answering questions using real documentation with ReAct-based reasoning"
        },
        "module_2": {
            "name": "Multi-Agent Systems",
            "weeks": "5-8",
            "topics": [
                "Agent design patterns",
                "Tool integration and function calling",
                "Multi-agent coordination",
                "LangGraph for complex workflows",
                "Human-in-the-loop systems",
                "Agent memory and state management"
            ],
            "project": "Multi-agent research assistant with human oversight using FastAPI and local LLM inference"
        },
        "module_3": {
            "name": "Real-World Readiness",
            "weeks": "9-12",
            "topics": [
                "Testing agentic AI systems",
                "Security and guardrails (OWASP Top 10 for LLMs)",
                "Deployment strategies",
                "Monitoring and observability",
                "Production best practices",
                "Safety and alignment testing"
            ],
            "project": "Transform multi-agent system into production-ready application with full testing suite"
        },
        "module_4": {
            "name": "Advanced Topics (Optional)",
            "weeks": "Post-certification",
            "topics": [
                "Alternative agent frameworks",
                "Context engineering",
                "Graph RAG",
                "Governance and fairness",
                "Advanced testing",
                "Production monitoring"
            ],
            "required": False
        }
    },
    "enrollment": {
        "process": [
            "Visit certifications page from top menu",
            "Select Agentic AI Developer Certification card",
            "Click 'Enroll for Free'",
            "Instant enrollment and access to all lessons"
        ],
        "flexibility": "Self-paced, can start any module based on experience",
        "access": "All 12 weeks of lessons unlocked immediately",
        "cohort": "Can join anytime, monthly project reviews"
    },
    "projects": {
        "requirements": "Must score 70% or higher on each project",
        "submission": "Submit on Ready Tensor platform",
        "review": "Projects reviewed monthly by Ready Tensor experts",
        "revision": "Can revise and resubmit if needed",
        "portfolio": "All projects become public portfolio pieces"
    }
}

# ============================================================================
# LANGGRAPH STATE AND AGENT DEFINITIONS
# ============================================================================

class AgentState(TypedDict):
    """State definition for the agent graph"""
    messages: Annotated[List, operator.add]
    query: str
    next_action: str


# Initialize tools list
tools = [web_search_tool, document_retrieval_tool, code_executor_tool]

# Create ToolNode
tool_node = ToolNode(tools)


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """
    Determine if we should call tools or end the conversation
    
    Args:
        state: Current agent state
    
    Returns:
        Next node to execute
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # If there are no tool calls, we're done
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        logger.info("No tool calls found, ending conversation")
        return "end"
    
    logger.info(f"Tool calls detected: {len(last_message.tool_calls)}")
    return "tools"


def call_model(state: AgentState) -> AgentState:
    """
    Call the LLM model with current state
    
    Args:
        state: Current agent state
    
    Returns:
        Updated state with model response
    """
    try:
        messages = state["messages"]
        logger.info(f"Calling model with {len(messages)} messages")
        
        # Get the LLM from user_session
        llm = cl.user_session.get("llm")
        if not llm:
            raise ValueError("LLM not initialized in session")
        
        # Bind tools to the model
        llm_with_tools = llm.bind_tools(tools)
        
        # Invoke the model
        response = llm_with_tools.invoke(messages)
        
        logger.info("Model invocation successful")
        return {"messages": [response]}
    
    except Exception as e:
        error_msg = f"Error calling model: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"messages": [AIMessage(content=f"⚠️ {error_msg}")]}


def format_tool_response(tool_result: dict, tool_name: str) -> str:
    """
    Format tool results into readable text
    
    Args:
        tool_result: Dictionary result from tool execution
        tool_name: Name of the tool that was called
    
    Returns:
        Formatted string for display
    """
    try:
        if tool_name == "web_search_tool":
            if tool_result.get("status") == "error":
                return f"❌ **Web Search Error**: {tool_result.get('message', 'Unknown error')}"
            
            output = f"🔍 **Web Search Results for '{tool_result.get('query', '')}'**\n\n"
            
            # Add answer if available
            if tool_result.get("answer"):
                output += f"**Quick Answer**: {tool_result['answer']}\n\n"
            
            # Add results
            results = tool_result.get("results", [])
            if results:
                output += f"**Found {len(results)} sources:**\n\n"
                for idx, result in enumerate(results, 1):
                    output += f"**{idx}. {result.get('title', 'No title')}**\n"
                    output += f"{result.get('content', 'No content')}\n"
                    output += f"🔗 [Source]({result.get('url', '#')})\n"
                    if result.get('published_date') and result['published_date'] != 'Unknown':
                        output += f"📅 {result['published_date']}\n"
                    output += "\n"
            else:
                output += "No results found.\n"
            
            return output
        
        elif tool_name == "document_retrieval_tool":
            if tool_result.get("status") == "error":
                return f"❌ **Document Retrieval Error**: {tool_result.get('message', 'Unknown error')}"
            
            if tool_result.get("status") == "not_found":
                available = ", ".join(tool_result.get("available_topics", []))
                return f"📚 {tool_result.get('message')}\n\n**Available topics**: {available}"
            
            output = f"📚 **Documentation for '{tool_result.get('topic', '')}'**\n\n"
            
            documents = tool_result.get("documents", [])
            for doc in documents:
                output += f"## {doc.get('title', 'Untitled')} (Module {doc.get('module', 'N/A')})\n\n"
                output += f"{doc.get('content', 'No content')}\n\n"
                output += "---\n\n"
            
            return output
        
        elif tool_name == "code_executor_tool":
            status = tool_result.get("status")
            
            if status == "error":
                return f"❌ **{tool_result.get('message', 'Execution Error')}**: {tool_result.get('details', '')}"
            
            if status == "blocked":
                return f"⚠️ **{tool_result.get('message', '')}**\n\n{tool_result.get('details', '')}"
            
            if status == "success":
                output = "✅ **Code executed successfully**\n\n"
                if tool_result.get("output"):
                    output += f"```\n{tool_result['output']}\n```"
                return output
        
        # Fallback
        return f"**Tool Result ({tool_name})**:\n```json\n{json.dumps(tool_result, indent=2)}\n```"
    
    except Exception as e:
        logger.error(f"Error formatting tool response: {str(e)}")
        return f"⚠️ Error formatting response: {str(e)}"


# ============================================================================
# LANGGRAPH WORKFLOW CONSTRUCTION
# ============================================================================

def create_graph():
    """
    Create and compile the LangGraph workflow
    
    Returns:
        Compiled graph
    """
    try:
        # Create the graph
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", tool_node)
        
        # Add edges
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "end": END
            }
        )
        workflow.add_edge("tools", "agent")
        
        # Compile the graph
        app = workflow.compile()
        
        logger.info("LangGraph workflow created and compiled successfully")
        return app
    
    except Exception as e:
        logger.error(f"Error creating graph: {str(e)}", exc_info=True)
        raise


# ============================================================================
# CHAINLIT UI INTEGRATION
# ============================================================================

@cl.on_chat_start
async def start():
    """Initialize chatbot when chat session starts"""
    try:
        # Validate environment
        validation = validate_environment()
        
        if not validation.get("GROQ_API_KEY"):
            await cl.Message(
                content="❌ **ERROR**: GROQ_API_KEY environment variable not set!\n\n"
                        "Please set it using:\n"
                        "```bash\n"
                        "export GROQ_API_KEY=your_key_here   # macOS/Linux\n"
                        "set GROQ_API_KEY=your_key_here      # Windows CMD\n"
                        "$env:GROQ_API_KEY=\"your_key_here\" # PowerShell\n"
                        "```"
            ).send()
            logger.critical("Chat session aborted: GROQ_API_KEY not set")
            return
        
        if not validation.get("TAVILY_API_KEY"):
            await cl.Message(
                content="⚠️ **WARNING**: TAVILY_API_KEY not set. Web search will not work.\n\n"
                        "Get a free key from: https://tavily.com/"
            ).send()
        
        # Initialize LLM
        groq_api_key = os.getenv("GROQ_API_KEY")
        llm = ChatGroq(
            api_key=groq_api_key,
            model="llama-3.1-8b-instant",
            temperature=0.3
        )
        
        # Store in session
        cl.user_session.set("llm", llm)
        cl.user_session.set("conversation_history", [])
        
        # Create graph
        graph = create_graph()
        cl.user_session.set("graph", graph)
        
        logger.info("New chat session started successfully")
        
        # Welcome message
        welcome_msg = """# 🤖 Ready Tensor Agentic AI Certification Chatbot

Welcome! I'm here to help you with the Agentic AI Certification program.

## 🔧 Available Tools:
- **🔍 Web Search** - Ask about latest news, current events, or say "search for..."
- **💻 Code Execution** - Share Python code in \`\`\`python blocks\`\`\`
- **📚 Documentation** - Ask about RAG, LangGraph, security, deployment, testing

## 💡 What can I help you with?
- Course content and modules
- Enrollment information  
- Technical questions
- Project requirements
- And much more!

**Try asking**: "Search for recent developments in AI agents" or "Tell me about the RAG module"
"""
        
        await cl.Message(content=welcome_msg).send()
        
    except Exception as e:
        error_msg = f"Failed to initialize chatbot: {str(e)}"
        logger.critical(error_msg, exc_info=True)
        await cl.Message(content=f"❌ {error_msg}").send()


@cl.on_message
async def main(message: cl.Message):
    """Handle incoming messages"""
    try:
        user_input = message.content.strip()
        
        if not user_input:
            await cl.Message(content="Please enter a message.").send()
            return
        
        # Get graph and history from session
        graph = cl.user_session.get("graph")
        history = cl.user_session.get("conversation_history", [])
        
        if not graph:
            await cl.Message(content="❌ Graph not initialized. Please refresh the page.").send()
            logger.error("Message received but graph not initialized")
            return
        
        # Special command: history
        if user_input.lower() in ['history', 'show history']:
            if not history:
                await cl.Message(content="📜 No conversation history yet.").send()
                return
            
            history_text = "# 📜 Conversation History\n\n"
            for i, item in enumerate(history[-10:], 1):
                history_text += f"{i}. **Q**: {item.get('query', '')[:80]}...\n"
            
            await cl.Message(content=history_text).send()
            logger.info("History displayed")
            return
        
        # Build system message
        system_message = SystemMessage(
            content=f"""You are a helpful assistant for the Ready Tensor Agentic AI Certification program.

KNOWLEDGE BASE:
{json.dumps(COURSE_KNOWLEDGE, indent=2)}

You have access to these tools:
1. web_search_tool - Search the web for current information
2. document_retrieval_tool - Get course documentation
3. code_executor_tool - Execute Python code

When users ask about:
- Recent/current events, news, updates → Use web_search_tool
- RAG, LangGraph, security, deployment, testing → Use document_retrieval_tool
- Code examples with ```python blocks → Use code_executor_tool

Be helpful, concise, and guide users to use tools when appropriate."""
        )
        
        # Create initial state
        initial_state = {
            "messages": [system_message, HumanMessage(content=user_input)],
            "query": user_input,
            "next_action": ""
        }
        
        # Show processing indicator
        msg = cl.Message(content="")
        await msg.send()
        
        # Run the graph
        logger.info(f"Processing query: {user_input[:100]}")
        final_state = None
        
        try:
            # Stream the graph execution
            async for state in graph.astream(initial_state, stream_mode="values"):
                final_state = state
        except Exception as e:
            error_msg = f"Error executing graph: {str(e)}"
            logger.error(error_msg, exc_info=True)
            msg.content = f"⚠️ {error_msg}"
            await msg.update()
            return
        
        if not final_state:
            msg.content = "⚠️ No response generated"
            await msg.update()
            return
        
        # Extract and format response
        messages = final_state.get("messages", [])
        response_content = ""
        
        # Process all messages to build response
        for msg_item in messages:
            if isinstance(msg_item, AIMessage):
                # Check if there are tool calls
                if hasattr(msg_item, "tool_calls") and msg_item.tool_calls:
                    # Tool calls are being made
                    pass
                elif msg_item.content:
                    # Regular AI response
                    response_content = msg_item.content
            
            elif isinstance(msg_item, ToolMessage):
                # Format tool results
                try:
                    tool_result = json.loads(msg_item.content)
                    tool_name = msg_item.name
                    formatted_result = format_tool_response(tool_result, tool_name)
                    response_content += f"\n\n{formatted_result}"
                except json.JSONDecodeError:
                    response_content += f"\n\n{msg_item.content}"
                except Exception as e:
                    logger.error(f"Error processing tool message: {str(e)}")
        
        # If no content was generated, use last AI message
        if not response_content:
            for msg_item in reversed(messages):
                if isinstance(msg_item, AIMessage) and msg_item.content:
                    response_content = msg_item.content
                    break
        
        if not response_content:
            response_content = "I apologize, but I couldn't generate a proper response. Please try rephrasing your question."
        
        # Update message with response
        msg.content = response_content
        await msg.update()
        
        # Save to history
        history.append({
            "query": user_input,
            "response": response_content,
            "timestamp": datetime.now().isoformat()
        })
        cl.user_session.set("conversation_history", history)
        
        logger.info(f"Response sent: {len(response_content)} characters")
        
    except Exception as e:
        error_msg = f"Error processing message: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await cl.Message(content=f"⚠️ {error_msg}").send()


@cl.on_chat_end
def end():
    """Clean up when chat session ends"""
    try:
        history = cl.user_session.get("conversation_history", [])
        logger.info(f"Chat session ended. History entries: {len(history)}")
    except Exception as e:
        logger.error(f"Error during chat cleanup: {str(e)}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    logger.info("Application started")
    
    # Validate environment
    validation = validate_environment()
    
    if not validation.get("GROQ_API_KEY"):
        logger.critical("GROQ_API_KEY not set. Exiting.")
        print("❌ ERROR: GROQ_API_KEY not set!")
        print("\nSet it using:")
        print("  export GROQ_API_KEY=your_key   # macOS/Linux")
        print("  set GROQ_API_KEY=your_key      # Windows")
        sys.exit(1)
    
    if not validation.get("TAVILY_API_KEY"):
        logger.warning("TAVILY_API_KEY not set. Web search will be unavailable.")
        print("⚠️  WARNING: TAVILY_API_KEY not set. Web search disabled.")
    
    print("\n" + "="*70)
    print("🤖 Ready Tensor Agentic AI Certification Chatbot")
    print("="*70)
    print("\n✅ Environment validated")
    print("🚀 To run with Chainlit UI, use:")
    print("   chainlit run <filename>.py -w")
    print("\n" + "="*70 + "\n")