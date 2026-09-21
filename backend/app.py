from flask import Flask, jsonify
import sys
import os


# =========================
# Project Root
# =========================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.append(PROJECT_ROOT)


# =========================
# Database
# =========================

from database.database import (
    get_db_connection,
    init_db
)


# =========================
# Routes
# =========================

from routes.auth import auth_bp
from routes.documents import documents_bp
from routes.rag import rag_bp
from routes.admin import admin_bp


# =========================
# Flask App
# =========================

app = Flask(__name__)


# =========================
# Session Configuration
# =========================

app.config["SECRET_KEY"] = "docurag-development-secret-key"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# =========================
# Initialize Database
# =========================

init_db()


# =========================
# Register Blueprints
# =========================

# Authentication
app.register_blueprint(
    auth_bp,
    url_prefix="/api"
)


# Documents
app.register_blueprint(
    documents_bp,
    url_prefix="/api/documents"
)


# RAG
app.register_blueprint(
    rag_bp,
    url_prefix="/api"
)


# Admin
app.register_blueprint(
    admin_bp,
    url_prefix="/api/admin"
)


# =========================
# Health Check
# =========================

@app.route("/api/health", methods=["GET"])
def health_check():

    try:

        connection = get_db_connection()

        connection.execute("SELECT 1")

        connection.close()

        return jsonify({
            "status": "success",
            "message": "DocuRAG backend and database are working"
        }), 200

    except Exception:

        return jsonify({
            "status": "error",
            "message": "Database connection failed"
        }), 500


# =========================
# Run Application
# =========================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )