import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth_api import auth_router
from backend.api.documents_api import documents_router
from backend.api.rag_api import rag_router
from backend.api.admin_api import admin_router


# ============================================================
# PATH SETUP
# ============================================================

CURRENT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(
    CURRENT_DIR
)

sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="DocuRAG REST API",
    description="AI Powered Document & Image Search and Analysis API",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# API ROUTERS
# ============================================================

# Authentication
app.include_router(
    auth_router
)

# Documents
app.include_router(
    documents_router
)

# RAG
app.include_router(
    rag_router
)

# Admin
app.include_router(
    admin_router
)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health_check():

    return {
        "status": "success",
        "message": "DocuRAG FastAPI is working"
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "application": "DocuRAG",
        "message": "DocuRAG FastAPI REST API",
        "version": "1.0.0"
    }