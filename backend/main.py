import os
from dotenv import load_dotenv

# 1. Load environment variables before importing graph or langchain
load_dotenv()

import traceback
import uuid
import asyncio
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import Optional
from langchain_core.messages import HumanMessage
from graph import app  # Your compiled LangGraph with MemorySaver

# --- QE LOGGING ---
print("\n" + "="*50)
project = os.getenv("LANGCHAIN_PROJECT")
if os.getenv("LANGCHAIN_TRACING_V2") == "true":
    print(f"✅ LANGSMITH TRACING ACTIVE: {project}")
else:
    print("⚠️  TRACING DISABLED: Check .env for LANGCHAIN_TRACING_V2=true")
print("="*50 + "\n")

server = FastAPI(title="Multi-Agent RAG: Human-in-the-Loop Backend")

class ChatRequest(BaseModel):
    query: str
    user_role: str = "viewer"
    session_id: Optional[str] = None 

# --- ENDPOINTS ---

@server.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """Initializes the graph or continues an existing session."""
    try:
        # SENIOR QE FIX: Ensure we reuse the session_id to maintain 'context' memory
        current_thread_id = request.session_id if request.session_id else str(uuid.uuid4())
        config = {
            "configurable": {"thread_id": current_thread_id},
            "tags": ["HITL_v2", f"role:{request.user_role}"],
            "metadata": {"user": "subhash_chellam", "platform": "WSL2"}
        }

        # Check if this thread already has a history in MemorySaver
        existing_state = await app.aget_state(config)

        if existing_state.values:
            print(f">> TRACE: Existing session {current_thread_id} found. Appending message.")
            # If session exists, we don't send 'initial_state', we just send the new message
            # This prevents the 'context' from being overwritten by an empty string
            await app.ainvoke(
                {"messages": [HumanMessage(content=request.query)]}, 
                config=config
            )
        else:
            print(f">> TRACE: Creating NEW session {current_thread_id}.")
            initial_state = {
                "messages": [HumanMessage(content=request.query)],
                "user_role": request.user_role,
                "context": "", # Fresh start
                "retry_count": 0,
                "feedback": ""
            }
            await app.ainvoke(initial_state, config=config)
        
        # After execution (or interrupt), get the latest snapshot
        snapshot = await app.aget_state(config)
        
        # Determine if we are at a checkpoint or finished
        if snapshot.next and "responder" in snapshot.next:
            return {
                "status": "pending_approval",
                "session_id": current_thread_id,
                "retrieved_context": snapshot.values.get("context", "No context retrieved"),
                "message": "Human review required for the retrieved documents."
            }

        return {
            "status": "complete",
            "response": snapshot.values["messages"][-1].content,
            "session_id": current_thread_id
        }

    except Exception as e:
        print(f"CRITICAL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@server.post("/approve")
async def approve_endpoint(payload: dict = Body(...)):
    """Resumes the graph to generate the final LLM response."""
    try:
        session_id = payload.get("session_id")
        config = {"configurable": {"thread_id": session_id}}
        
        # 1. Update state with approval
        await app.aupdate_state(config, {"feedback": "APPROVED"})
        
        # 2. Resume execution
        # Passing None tells LangGraph to resume from where it stopped (the responder)
        result = await app.ainvoke(None, config=config)
        
        return {
            "status": "complete",
            "response": result["messages"][-1].content,
            "session_id": session_id
        }
    except Exception as e:
        print(f"APPROVE ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to resume: {str(e)}")

@server.post("/reject")
async def reject_endpoint(payload: dict = Body(...)):
    """Resumes the graph but routes to the Query Optimizer for re-retrieval."""
    try:
        session_id = payload.get("session_id")
        feedback = payload.get("feedback", "Please optimize the search.")
        config = {"configurable": {"thread_id": session_id}}
        
        # 1. Update state with the human's specific feedback
        await app.aupdate_state(config, {"feedback": feedback})
        
        # 2. Resume: Will trigger route_after_human_review -> query_optimizer
        await app.ainvoke(None, config=config)
        
        snapshot = await app.aget_state(config)
        
        return {
            "status": "pending_approval",
            "session_id": session_id,
            "retrieved_context": snapshot.values.get("context"),
            "message": "Re-retrieval complete based on your feedback."
        }
    except Exception as e:
        print(f"REJECT ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to initiate re-query loop.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(server, host="0.0.0.0", port=8080)