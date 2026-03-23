import streamlit as st
import requests

st.set_page_config(page_title="Multi-Agent RAG", layout="wide")

# --- UI Header ---
st.title("🤖 Capstone Multi-Agent RAG")
st.subheader("Developed By Subhash Chellam R")

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("Security Settings")
    role = st.selectbox("Current User Role", ["admin", "viewer"])
    st.info(f"Acting as: {role}")
    
    st.divider()
    
    # QE Tool: Reset Chat Session
    if st.button("🗑️ Clear Chat History"):
        st.session_state.messages = []
        st.rerun()

# --- Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Display Chat History ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- User Input & Backend Interaction ---
if prompt := st.chat_input("Ask about your enterprise data..."):
    # Add user message to state and UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call FastAPI Backend (Running on Port 8080)
    with st.chat_message("assistant"):
        try:
            payload = {"query": prompt, "user_role": role}
            # Ensure the backend is running at this address
            response = requests.post("http://localhost:8080/chat", json=payload, timeout=120)
            
            if response.status_code == 200:
                data = response.json()
                
                # Defensive key handling: Prevents 'KeyError' if keys are missing
                full_response = data.get("response", "No response content returned.")
                context_used = data.get("context_used", "No source context available.")
                
                # Display the Answer
                st.markdown(full_response)
                
                # Transparency/QE Debugging: Show the RAG context
                with st.expander("🔍 View Source Context (RAG)"):
                    st.info(context_used)
                
                # Save assistant message to history
                st.session_state.messages.append({"role": "assistant", "content": full_response})
            
            else:
                st.error(f"Backend Error ({response.status_code}): Check WSL Terminal logs.")
                
        except requests.exceptions.ConnectionError:
            st.error("Connection failed: Is the FastAPI backend running on port 8080?")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")