import os
import subprocess
import re
import psycopg2 
import random
from datetime import datetime, date, timedelta
from typing import Annotated, Sequence, TypedDict, Literal
from dotenv import load_dotenv

# --- 1. INITIALIZATION ---
load_dotenv()

from utils.scrubber import redact_pii
from langchain_huggingface import HuggingFaceEmbeddings  
from langchain_chroma import Chroma
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver 

def get_wsl_host_ip():
    try:
        host_ip = subprocess.check_output("ip route show | grep default | awk '{print $3}'", shell=True).decode().strip()
        return host_ip if host_ip else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

WINDOWS_HOST = get_wsl_host_ip()

# --- 2. DB CONFIGURATION & GUARDRAILS ---
DB_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "mysecretpassword", 
    "host": "localhost",
    "port": "5432"
}

DB_SCHEMA = """
Table: retail_leads
Columns: id (INT), cust_name (TEXT), email (TEXT), phone (TEXT), product (TEXT), value (FLOAT), region (TEXT), status (TEXT)
"""

SEMANTIC_MAPPINGS = {
    "high value": "value > 100000",
    "pending": "status = 'IN_PROGRESS'",
    "south": "region = 'SOUTH_INDIA'"
}

def is_sql_safe(query: str) -> bool:
    """SQL Guardrail: Blocks destructive commands."""
    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "GRANT"]
    return not any(word in query.upper() for word in forbidden)

# --- 3. STATE DEFINITION ---
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    context: str
    user_role: str
    is_authorized: bool
    retry_count: int
    feedback: str 
    detected_intent: str  # NEW: Tracks if this turn is 'data', 'knowledge', or 'both'
    # Added to track the bypass status
    approval_required: bool

# --- 4. TOOLS ---
@tool
def fetch_enterprise_knowledge(query: str):
    """
    Searches the internal vector database (ChromaDB) to retrieve banking guidelines.
    """
    embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings,
        collection_name="enterprise_docs"
    )
    docs = vectorstore.similarity_search(query, k=3)
    return "\n\n".join([d.page_content for d in docs])

# --- 5. NODE IMPLEMENTATIONS ---

def security_gatekeeper(state: AgentState):
    print("\n" + "="*40)
    print("[NODE: SECURITY GATEKEEPER]")
    last_msg = state["messages"][-1].content
    clean_text = redact_pii(last_msg)
    
    sanitized_msg = []
    if clean_text != last_msg:
        print(">> TRACE [SECURITY]: PII detected and redacted from input.")
        sanitized_msg = [HumanMessage(content=clean_text)]

    user_role = state.get("user_role", "qa_lead").lower()
    authorized = user_role in ["admin", "internal", "qa_lead"]
    
    print(f">> TRACE [SECURITY]: Role: {user_role} | Authorized: {authorized}")
    return {"is_authorized": authorized, "retry_count": 0, "messages": sanitized_msg}

def intent_router(state: AgentState) -> Literal["sql_engine", "rag_agent", "unauthorized"]:
    print("\n" + "="*30)
    print("[NODE: INTENT ROUTER]")
    
    if not state.get("is_authorized", False):
        return "unauthorized"

    last_msg = state["messages"][-1].content.lower()
    full_context = state.get("context", "")
    # 1. DEFINE TRIGGERS
    recall_triggers = ["remind", "who were", "list them again", "those customers", "previous list", "recall"]
    data_triggers = ["customer", "lead", "who", "contact", "list", "details", "names","top", "branches", "savings", "last quarter", "count", "list", "disbursement","average",
                     "turnaround time", "personal loan", "approval", "region","customers", "failed transactions", 
                     "Total", "disbursement"]
    knowledge_triggers = ["interest rate", "policy", "guideline", "rbi", "how to", "percentage", "apr"]

    # 2. LOGIC: SCENARIO-BASED INTENT SETTING
    
    # Scenario C: RECALL (Memory) - User wants to see old data again
    if any(word in last_msg for word in recall_triggers):
        # Check if we actually have DATABASE_RESULT in our memory
        if "DATABASE_RESULT" in full_context and "Data: []" not in full_context:
            print(">> TRACE [ROUTER]: Recall Intent. Memory found.")
            state["detected_intent"] = "recall"
        else:
            print(">> TRACE [ROUTER]: Recall Intent. MEMORY IS EMPTY.")
            state["detected_intent"] = "recall_empty"
        return "rag_agent"

    # Scenario B: KNOWLEDGE (RAG Only) - "What is the interest rate?"
    if any(word in last_msg for word in knowledge_triggers) and not any(word in last_msg for word in data_triggers):
        print(">> TRACE [ROUTER]: Detected 'KNOWLEDGE' Intent (RAG Only).")
        state["detected_intent"] = "knowledge_only"
        return "rag_agent"

    # Scenario A: DATA (SQL) - "Get me customers..."
    if any(word in last_msg for word in data_triggers):
        print(">> TRACE [ROUTER]: Detected 'DATA' Intent (SQL Engine).")
        state["detected_intent"] = "data"
        return "sql_engine"

    # Default
    state["detected_intent"] = "combined"
    return "rag_agent"

def sql_engine_node(state: AgentState):
    print("\n" + "-"*30)
    print("[NODE: SQL ENGINE - LITERAL TRANSLATOR]")
    llm = ChatOllama(model="llama3", base_url=f"http://{WINDOWS_HOST}:11434", temperature=0)
    query = state["messages"][-1].content

    today = date.today()
    # Logic to find the first and last day of the PREVIOUS month
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    
    current_context = f"Today's Date: {today} | Previous Month Range: {first_day_prev_month} to {last_day_prev_month}"

    # --- THE SCHEMA & ISOLATION RULES ---
    database_schema = """
    1. Table: branch_performance [branch_name, savings_accounts_opened, opening_date]
    2. Table: loan_applications [loan_type, region, applied_date, approval_date, status]
    3. Table: disbursements [product_type, amount, disbursement_date]
    4. Table: transactions [customer_name, status, transaction_time]
    """

    prompt = f"""
    [SYSTEM RULE: ZERO-KNOWLEDGE MODE]
    You are a SQL Translator. You have NO knowledge of banking outside of the provided [DATABASE SCHEMA].
    IF a query cannot be answered by the schema, return: "ERROR: DATA_NOT_FOUND".
    DO NOT use your internal training data to invent results.

    [TEMPORAL CONTEXT]
    {current_context}

    [DATABASE SCHEMA]
    {database_schema}

    STRICT GENERATION RULES:
    1. USE ONLY the columns requested. If "contact details" are asked, SELECT cust_name, email, phone.
    2. DO NOT add extra WHERE clauses (like status='Active') unless the user explicitly mentions them.
    3. Use 'ILIKE' for string matching (e.g., product ILIKE '%home loan%').
    4. IGNORE keywords like 'policy', 'RBI', or 'rules'. Those are for the RAG agent.
    5. OUTPUT FORMAT: Return the raw SQL only. No explanations. No preamble.
    6. Ensure the query ends with a semicolon ';'.
    7. 'Previous Month' MUST use the range: {first_day_prev_month} AND {last_day_prev_month}.
    8. 'Last 7 Days' MUST calculate from {today}.
    9. Return ONLY the raw PostgreSQL code. No preamble or conversational text.
    
    USER REQUEST: {query}
    """
    
    try:
        response = llm.invoke(prompt).content.strip()
        
        # --- ROBUST EXTRACTION (Fixes the "meets" error) ---
        # We look for the LAST occurrence of 'SELECT' to skip any "Here is the SELECT..." intro text
        last_select_idx = response.upper().rfind("SELECT")
        
        if last_select_idx != -1:
            generated_sql = response[last_select_idx:].strip()
            # Clean up markdown and trailing text
            generated_sql = generated_sql.split(';')[0].split('```')[0].strip() + ";"
        else:
            print(f">> TRACE [SQL ERROR]: No SELECT statement found in: {response}")
            return {"context": "Error: SQL Generation failed."}

        # Final Clean: Remove single quotes from column names if LLM added them
        generated_sql = generated_sql.replace("'cust_name'", "cust_name").replace("'email'", "email").replace("'phone'", "phone")

        print(f">> TRACE [SQL]: Final Validated Query: {generated_sql}")

        if not is_sql_safe(generated_sql):
            return {"context": "Error: Destructive SQL blocked."}

        # Execution
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(generated_sql)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        cur.close(); conn.close()
        
        print(f">> TRACE [SQL]: Success. {len(rows)} records retrieved.")
        return {"context": f"DATABASE_RESULT: Columns: {colnames} | Data: {rows}"}

    except Exception as e:
        print(f">> TRACE [SQL EXECUTION ERROR]: {str(e)}")
        return {"context": f"Database Error: {str(e)}"}

def rag_retriever(state: AgentState):
    print("\n[NODE: RAG RETRIEVER]")
    # Search based on the last message
    query = state["messages"][-1].content
    existing_context = state.get("context", "")
    
    print(f">> TRACE [RAG]: Searching Knowledge Base for: {query}")
    try:
        raw_rag_context = fetch_enterprise_knowledge.invoke(query)
        # We append so the state preserves previous SQL results if needed
        combined_context = f"{existing_context}\n\nRELEVANT POLICIES:\n{raw_rag_context}"
        return {"context": redact_pii(combined_context), "retry_count": 0}
    except Exception as e:
        print(f">> TRACE [RAG ERROR]: {e}")
        return {"retry_count": state.get("retry_count", 0) + 1}

def query_optimizer(state: AgentState):
    print("\n[NODE: QUERY OPTIMIZER]")
    llm = ChatOllama(model="llama3", base_url=f"http://{WINDOWS_HOST}:11434", temperature=0)
    prompt = f"Optimize query based on feedback '{state.get('feedback', 'None')}': {state['messages'][0].content}"
    return {"messages": [HumanMessage(content=llm.invoke(prompt).content)]}

def responder_node(state: AgentState):
    print("\n" + "="*40)
    print("[NODE: RESPONDER - STRICT CONTEXT PARTITIONING]")
    llm = ChatOllama(model="llama3", base_url=f"http://{WINDOWS_HOST}:11434", temperature=0)
    
    current_query = state['messages'][-1].content
    full_context = state.get('context', '')
    intent = state.get("detected_intent", "combined")

    # --- STEP 1: PHYSICAL SEPARATION OF DATA ---
    # We split the long context string into two distinct variables
    sql_mem = ""
    rag_mem = ""
    
    if "DATABASE_RESULT:" in full_context:
        parts = full_context.split("RELEVANT POLICIES:")
        sql_mem = parts[0].strip()
        if len(parts) > 1:
            rag_mem = "RELEVANT POLICIES:" + parts[1].strip()

    # --- STEP 2: THE FIREWALL (Intent-Based Masking) ---
    # We explicitly EMPTY the variable the LLM shouldn't see
    if intent == "knowledge_only":
        print(f">> TRACE [RESPONDER]: Intent is {intent}. SHIELDING Customer Data from LLM.")
        active_sql_context = "SOURCE_SQL: [NO_DATA_AVAILABLE_FOR_THIS_INTENT]"
        active_rag_context = f"SOURCE_RAG: {rag_mem}"
        system_instruction = (
            "You are a General Policy Assistant. "
            "STRICT RULE: You do not have access to any customer database. "
            "DO NOT mention names, emails, or phone numbers. "
            "Focus ONLY on the policy provided below."
            "Use ONLY the SOURCE_RAG data."
        )
    elif intent == "data" or intent == "recall":
        print(f">> TRACE [RESPONDER]: Intent is {intent}. Focusing on Customer Data.")
        active_sql_context = f"SOURCE_SQL: {sql_mem}"
        active_rag_context = "SOURCE_RAG: [NO_DATA_AVAILABLE_FOR_THIS_INTENT]"
        system_instruction = (
            "You are a Database Data Specialist."
            "Use ONLY the SOURCE_SQL data."
        )
    else:
        # Turn 1: Show everything
        active_sql_context = f"SOURCE_SQL: {sql_mem}"
        active_rag_context = f"SOURCE_RAG: {rag_mem}"
        system_instruction = (
            "You are a Banking Assistant."
            "Integrate both SOURCE_SQL and SOURCE_RAG sources."
        )

    # --- STEP 3: THE "ZERO-LEAK" PROMPT ---
    prompt = f"""
    You are a grounded Banking Assistant. Provide a direct, conversational response.

    [INTERNAL REFERENCE - DO NOT REPEAT VERBATIM]
    {system_instruction}

    [AVAILABLE CUSTOMER RECORDS]
    {active_sql_context}
    
    [AVAILABLE POLICY DOCUMENTS]
    {active_rag_context}
    
    USER QUESTION: {current_query}
    
    STRICT RULES:
    1. Summarize the INTERNAL REFERENCE into a clean response.
    2. DO NOT include technical headers like "DATABASE_RESULT", "Columns:", or "RELEVANT POLICIES" in your answer.
    3. DO NOT repeat the headers "[AVAILABLE CUSTOMER RECORDS]" or "[INTERNAL REFERENCE]".
    4. Format any contact details as a clean Markdown list.
    5. If CUSTOMER_RECORDS says "NO CUSTOMER DATA", do not mention any names or personal info.
    """
    
    print(f">> TRACE [RESPONDER]: Sending Partitioned Prompt to LLM.")
    response = llm.invoke(prompt)

    # --- STEP 4: POST-PROCESSING STRIP (Final Safety) ---
    clean_content = response.content
    # Programmatic check to delete the "Customer Details" section if it leaked
    if intent == "knowledge_only" and "Customer Details" in clean_content:
        print(">> TRACE [QE ALERT]: LLM attempted to leak PII. Stripping section.")
        clean_content = clean_content.split("Customer Details")[0].strip()

    response.content = clean_content
    print("="*40)
    return {"messages": [response]}

# --- 6. ROUTING LOGIC ---

def route_after_rag(state: AgentState):
    if state.get("retry_count", 0) > 0 and state["retry_count"] < 3:
        return "retry"
    return "continue"

def route_after_human_review(state: AgentState):
    print("\n[ROUTING: HUMAN-IN-THE-LOOP CHECK]")
    
    # 1. Read external property (from .env or OS)
    # Default to 'FALSE' (Automated) if the property is missing
    is_manual_mode = os.getenv("REQUIRE_HUMAN_APPROVAL", "FALSE").upper() == "TRUE"
    
    if not is_manual_mode:
        print(">> TRACE [ROUTER]: External Config set to AUTOMATED. Bypassing review.")
        return "approved"

    # 2. If Manual Mode is ENABLED, check the feedback state
    feedback = state.get("feedback", "PENDING").upper()
    print(f">> TRACE [ROUTER]: Manual Mode ACTIVE. Current Feedback: {feedback}")

    if feedback == "APPROVED":
        return "approved"
    elif feedback == "REJECTED":
        return "rejected"
    
    # Stay at responder/interrupt if no valid feedback is found
    return "rejected"

# --- 7. GRAPH CONSTRUCTION ---
workflow = StateGraph(AgentState)

workflow.add_node("security", security_gatekeeper)
workflow.add_node("rag_agent", rag_retriever)
workflow.add_node("sql_engine", sql_engine_node)
workflow.add_node("query_optimizer", query_optimizer)
workflow.add_node("responder", responder_node)

workflow.set_entry_point("security")

workflow.add_conditional_edges("security", intent_router, {
    "sql_engine": "sql_engine",
    "rag_agent": "rag_agent",
    "unauthorized": "responder"
})

workflow.add_edge("sql_engine", "rag_agent")

workflow.add_conditional_edges("rag_agent", route_after_rag, {
    "retry": "rag_agent",
    "continue": "responder"
})

workflow.add_conditional_edges("responder", route_after_human_review, {
    "approved": END,
    "rejected": "query_optimizer"
})

workflow.add_edge("query_optimizer", "security")

memory = MemorySaver()

is_manual_mode = os.getenv("REQUIRE_HUMAN_APPROVAL", "FALSE").upper() == "TRUE"

if is_manual_mode:
    print(">> TRACE [INIT]: Compiling with INTERRUPT (Manual Approval Enabled).")
    # memory must be defined earlier (e.g., memory = MemorySaver())
    app = workflow.compile(checkpointer=memory, interrupt_before=["responder"]) 
else:
    print(">> TRACE [INIT]: Compiling in SILENT MODE (Fully Automated).")
    app = workflow.compile(checkpointer=memory)