import streamlit as st
import requests
import uuid

# --- 1. CONFIGURATION ---
BACKEND_URL = "http://localhost:8080"

st.set_page_config(page_title="Capstone Multi-Agent RAG", layout="wide")

# Initialize persistent session state
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_hitl" not in st.session_state:
    st.session_state.pending_hitl = False
if "current_context" not in st.session_state:
    st.session_state.current_context = ""

# --- 2. UI HEADER ---
st.title("🤖 Capstone Multi-Agent RAG")
st.subheader("Developed By Subhash Chellam R")

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("Security Settings")
    role = st.selectbox("Current User Role", ["admin", "internal", "qa_lead", "viewer"])
    st.info(f"Session ID: {st.session_state.session_id}")
    
    if st.button("🗑️ Clear Chat History"):
        st.session_state.messages = []
        st.session_state.pending_hitl = False
        st.session_state.session_id = str(uuid.uuid4()) # Fresh session
        st.rerun()

# --- 4. CHAT HISTORY ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 5. INTERACTION LOGIC ---
if prompt := st.chat_input("Ask about RBI Retail Banking products..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Initial Chat Call
    with st.spinner("Agent orchestrating..."):
        payload = {
            "query": prompt, 
            "user_role": role, 
            "session_id": st.session_state.session_id
        }
        try:
            response = requests.post(f"{BACKEND_URL}/chat", json=payload).json()
            
            if response.get("status") == "pending_approval":
                st.session_state.pending_hitl = True
                st.session_state.current_context = response.get("retrieved_context")
                st.rerun() # Refresh to show HITL buttons
            else:
                answer = response.get("response", "No response content returned.")
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.rerun()
        except Exception as e:
            st.error(f"Backend Error: {e}")

# --- 6. HUMAN-IN-THE-LOOP OVERLAY ---
if st.session_state.pending_hitl:
    st.divider()
    st.warning("⚠️ **Human-in-the-Loop: Review Retrieved Context**")
    
    with st.expander("🔍 Scrutinize Scrubbed Context", expanded=True):
        st.info(st.session_state.current_context)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Approve & Generate Final Answer", use_container_width=True):
            res = requests.post(f"{BACKEND_URL}/approve", 
                                json={"session_id": st.session_state.session_id}).json()
            st.session_state.messages.append({"role": "assistant", "content": res.get("response")})
            st.session_state.pending_hitl = False
            st.rerun()

    with col2:
        feedback = st.text_input("Rejection Feedback:", placeholder="e.g., Focus specifically on RBI master circulars...")
        if st.button("🔄 Reject & Optimize Search", use_container_width=True):
            res = requests.post(f"{BACKEND_URL}/reject", 
                                json={"session_id": st.session_state.session_id, "feedback": feedback}).json()
            # Update the context with new results from the optimizer
            st.session_state.current_context = res.get("retrieved_context")
            st.success("Query Optimized. Please review new context above.")
            st.rerun()