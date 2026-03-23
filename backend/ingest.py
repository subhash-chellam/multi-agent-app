import os
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

load_dotenv()

DATA_PATH = "./data"  
CHROMA_PATH = "./chroma_db"

print("--- LOADING EMBEDDING MODEL ---")
embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-large-en-v1.5")

def ingest_docs():
    if not os.path.exists(DATA_PATH):
        os.makedirs(DATA_PATH)
        return

    print(f"--- LOADING DOCUMENTS FROM {DATA_PATH} ---")
    
    extensions = ["*.pdf", "*.docx", "*.doc", "*.html"]
    all_documents = []

    for ext in extensions:
        print(f"Scanning for {ext} files...")
        loader = DirectoryLoader(
            DATA_PATH, 
            glob=ext, 
            loader_cls=UnstructuredFileLoader,
            # QE FIX: silent_errors=True prevents 1 corrupt file from stopping the whole script
            silent_errors=True, 
            show_progress=True
        )
        try:
            docs = loader.load()
            all_documents.extend(docs)
        except Exception as e:
            print(f">> WARNING: Skipping some files in {ext} due to: {e}")

    if not all_documents:
        print("❌ No valid documents were loaded. Check your dependencies.")
        return

    print(f"Total Loaded: {len(all_documents)} document parts.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True
    )
    chunks = text_splitter.split_documents(all_documents)
    
    print("--- UPDATING VECTOR DATABASE ---")
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_PATH,
        collection_name="enterprise_docs"
    )
    print("✅ Ingestion Complete!")

if __name__ == "__main__":
    ingest_docs()