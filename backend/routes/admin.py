from flask import Blueprint, jsonify, request, session
from database.database import get_db_connection


# =========================
# Admin Blueprint
# =========================

admin_bp = Blueprint("admin", __name__)


# =========================
# Admin Authorization
# =========================

def require_admin():

    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id:
        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401

    if role != "admin":
        return jsonify({
            "status": "error",
            "message": "Admin access required"
        }), 403

    return None


# =========================
# Admin Statistics
# =========================

@admin_bp.route("/statistics", methods=["GET"])
def get_statistics():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        # Total users
        total_users = connection.execute("""
            SELECT COUNT(*) AS count
            FROM users
        """).fetchone()["count"]

        # Active users
        active_users = connection.execute("""
            SELECT COUNT(*) AS count
            FROM users
            WHERE is_active = 1
        """).fetchone()["count"]

        # Inactive users
        inactive_users = connection.execute("""
            SELECT COUNT(*) AS count
            FROM users
            WHERE is_active = 0
        """).fetchone()["count"]

        # Total documents
        total_documents = connection.execute("""
            SELECT COUNT(*) AS count
            FROM documents
        """).fetchone()["count"]

        # Processing documents
        processing_documents = connection.execute("""
            SELECT COUNT(*) AS count
            FROM documents
            WHERE processing_status = 'processing'
        """).fetchone()["count"]

        # Completed documents
        completed_documents = connection.execute("""
            SELECT COUNT(*) AS count
            FROM documents
            WHERE processing_status = 'completed'
        """).fetchone()["count"]

        # Failed documents
        failed_documents = connection.execute("""
            SELECT COUNT(*) AS count
            FROM documents
            WHERE processing_status = 'failed'
        """).fetchone()["count"]

        # Total queries
        total_queries = connection.execute("""
            SELECT COUNT(*) AS count
            FROM queries
        """).fetchone()["count"]

        # Total chunks
        total_chunks = connection.execute("""
            SELECT COUNT(*) AS count
            FROM document_chunks
        """).fetchone()["count"]

        # Total image analysis records
        total_images = connection.execute("""
            SELECT COUNT(*) AS count
            FROM image_analysis
        """).fetchone()["count"]

        return jsonify({
            "status": "success",
            "statistics": {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": inactive_users,
                "total_documents": total_documents,
                "processing_documents": processing_documents,
                "completed_documents": completed_documents,
                "failed_documents": failed_documents,
                "total_queries": total_queries,
                "total_chunks": total_chunks,
                "total_images": total_images
            }
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load statistics",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Get All Users
# =========================

@admin_bp.route("/users", methods=["GET"])
def get_users():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        users = connection.execute("""
            SELECT
                id,
                username,
                email,
                role,
                is_active,
                last_login,
                created_at,
                updated_at
            FROM users
            ORDER BY created_at DESC
        """).fetchall()

        users_list = []

        for user in users:

            users_list.append({
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
                "is_active": bool(user["is_active"]),
                "last_login": user["last_login"],
                "created_at": user["created_at"],
                "updated_at": user["updated_at"]
            })

        return jsonify({
            "status": "success",
            "users": users_list,
            "count": len(users_list)
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load users",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Activate User
# =========================

@admin_bp.route("/users/<int:user_id>/activate", methods=["PUT"])
def activate_user(user_id):

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        user = connection.execute("""
            SELECT id, username, role
            FROM users
            WHERE id = ?
        """, (user_id,)).fetchone()

        if not user:

            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        connection.execute("""
            UPDATE users
            SET
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user_id,))

        connection.commit()

        return jsonify({
            "status": "success",
            "message": f"User '{user['username']}' activated successfully"
        }), 200

    except Exception as e:

        connection.rollback()

        return jsonify({
            "status": "error",
            "message": "Failed to activate user",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Deactivate User
# =========================

@admin_bp.route("/users/<int:user_id>/deactivate", methods=["PUT"])
def deactivate_user(user_id):

    auth_error = require_admin()

    if auth_error:
        return auth_error

    current_admin_id = session.get("user_id")

    # Prevent admin from deactivating their own account
    if user_id == current_admin_id:

        return jsonify({
            "status": "error",
            "message": "You cannot deactivate your own admin account"
        }), 400

    connection = get_db_connection()

    try:

        user = connection.execute("""
            SELECT id, username, role
            FROM users
            WHERE id = ?
        """, (user_id,)).fetchone()

        if not user:

            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        connection.execute("""
            UPDATE users
            SET
                is_active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (user_id,))

        connection.commit()

        return jsonify({
            "status": "success",
            "message": f"User '{user['username']}' deactivated successfully"
        }), 200

    except Exception as e:

        connection.rollback()

        return jsonify({
            "status": "error",
            "message": "Failed to deactivate user",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Get All Documents
# =========================

@admin_bp.route("/documents", methods=["GET"])
def get_documents():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        documents = connection.execute("""
            SELECT
                d.id,
                d.filename,
                d.original_filename,
                d.file_type,
                d.file_size,
                d.upload_date,
                d.uploader_id,
                d.processing_status,
                d.page_count,
                d.error_message,
                d.processed_at,
                d.created_at,
                d.updated_at,
                u.username AS uploader_username,
                u.email AS uploader_email
            FROM documents d
            LEFT JOIN users u
                ON d.uploader_id = u.id
            ORDER BY d.created_at DESC
        """).fetchall()

        documents_list = []

        for document in documents:

            documents_list.append({
                "id": document["id"],
                "filename": document["filename"],
                "original_filename": document["original_filename"],
                "file_type": document["file_type"],
                "file_size": document["file_size"],
                "upload_date": document["upload_date"],
                "uploader_id": document["uploader_id"],
                "uploader_username": document["uploader_username"],
                "uploader_email": document["uploader_email"],
                "processing_status": document["processing_status"],
                "page_count": document["page_count"],
                "error_message": document["error_message"],
                "processed_at": document["processed_at"],
                "created_at": document["created_at"],
                "updated_at": document["updated_at"]
            })

        return jsonify({
            "status": "success",
            "documents": documents_list,
            "count": len(documents_list)
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load documents",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Get Failed Documents
# =========================

@admin_bp.route("/processing-failures", methods=["GET"])
def get_processing_failures():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        documents = connection.execute("""
            SELECT
                d.id,
                d.filename,
                d.original_filename,
                d.file_type,
                d.processing_status,
                d.error_message,
                d.upload_date,
                d.uploader_id,
                u.username AS uploader_username,
                u.email AS uploader_email
            FROM documents d
            LEFT JOIN users u
                ON d.uploader_id = u.id
            WHERE d.processing_status = 'failed'
            ORDER BY d.created_at DESC
        """).fetchall()

        failures = []

        for document in documents:

            failures.append({
                "id": document["id"],
                "filename": document["filename"],
                "original_filename": document["original_filename"],
                "file_type": document["file_type"],
                "processing_status": document["processing_status"],
                "error_message": document["error_message"],
                "upload_date": document["upload_date"],
                "uploader_id": document["uploader_id"],
                "uploader_username": document["uploader_username"],
                "uploader_email": document["uploader_email"]
            })

        return jsonify({
            "status": "success",
            "failures": failures,
            "count": len(failures)
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load processing failures",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Get All Queries
# =========================

@admin_bp.route("/queries", methods=["GET"])
def get_queries():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        queries = connection.execute("""
            SELECT
                q.id,
                q.user_id,
                q.conversation_id,
                q.question,
                q.answer,
                q.confidence,
                q.response_time,
                q.cache_hit,
                q.created_at,
                u.username,
                u.email
            FROM queries q
            LEFT JOIN users u
                ON q.user_id = u.id
            ORDER BY q.created_at DESC
            LIMIT 100
        """).fetchall()

        queries_list = []

        for query in queries:

            queries_list.append({
                "id": query["id"],
                "user_id": query["user_id"],
                "username": query["username"],
                "email": query["email"],
                "conversation_id": query["conversation_id"],
                "question": query["question"],
                "answer": query["answer"],
                "confidence": query["confidence"],
                "response_time": query["response_time"],
                "cache_hit": bool(query["cache_hit"]),
                "created_at": query["created_at"]
            })

        return jsonify({
            "status": "success",
            "queries": queries_list,
            "count": len(queries_list)
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load queries",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Get Single Document Details
# =========================

@admin_bp.route("/documents/<int:document_id>", methods=["GET"])
def get_document_details(document_id):

    auth_error = require_admin()

    if auth_error:
        return auth_error

    connection = get_db_connection()

    try:

        document = connection.execute("""
            SELECT
                d.*,
                u.username AS uploader_username,
                u.email AS uploader_email
            FROM documents d
            LEFT JOIN users u
                ON d.uploader_id = u.id
            WHERE d.id = ?
        """, (document_id,)).fetchone()

        if not document:

            return jsonify({
                "status": "error",
                "message": "Document not found"
            }), 404

        chunks_count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM document_chunks
            WHERE document_id = ?
        """, (document_id,)).fetchone()["count"]

        images_count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM image_analysis
            WHERE document_id = ?
        """, (document_id,)).fetchone()["count"]

        sources_count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM query_sources
            WHERE document_id = ?
        """, (document_id,)).fetchone()["count"]

        result = {
            "id": document["id"],
            "filename": document["filename"],
            "original_filename": document["original_filename"],
            "file_type": document["file_type"],
            "file_size": document["file_size"],
            "file_path": document["file_path"],
            "upload_date": document["upload_date"],
            "uploader_id": document["uploader_id"],
            "uploader_username": document["uploader_username"],
            "uploader_email": document["uploader_email"],
            "processing_status": document["processing_status"],
            "page_count": document["page_count"],
            "error_message": document["error_message"],
            "processed_at": document["processed_at"],
            "created_at": document["created_at"],
            "updated_at": document["updated_at"],
            "chunks_count": chunks_count,
            "images_count": images_count,
            "sources_count": sources_count
        }

        return jsonify({
            "status": "success",
            "document": result
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": "Failed to load document details",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Delete User
# =========================

@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):

    auth_error = require_admin()

    if auth_error:
        return auth_error

    current_admin_id = session.get("user_id")

    # Prevent self deletion
    if user_id == current_admin_id:

        return jsonify({
            "status": "error",
            "message": "You cannot delete your own admin account"
        }), 400

    connection = get_db_connection()

    try:

        user = connection.execute("""
            SELECT id, username, role
            FROM users
            WHERE id = ?
        """, (user_id,)).fetchone()

        if not user:

            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        # Documents reference users without ON DELETE CASCADE.
        # Therefore prevent deletion when the user owns documents.
        documents_count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM documents
            WHERE uploader_id = ?
        """, (user_id,)).fetchone()["count"]

        if documents_count > 0:

            return jsonify({
                "status": "error",
                "message": (
                    "User cannot be deleted because they have uploaded "
                    f"{documents_count} document(s). Deactivate the user instead."
                )
            }), 409

        connection.execute("""
            DELETE FROM users
            WHERE id = ?
        """, (user_id,))

        connection.commit()

        return jsonify({
            "status": "success",
            "message": f"User '{user['username']}' deleted successfully"
        }), 200

    except Exception as e:

        connection.rollback()

        return jsonify({
            "status": "error",
            "message": "Failed to delete user",
            "error": str(e)
        }), 500

    finally:

        connection.close()


# =========================
# Admin Health Check
# =========================

@admin_bp.route("/health", methods=["GET"])
def admin_health():

    auth_error = require_admin()

    if auth_error:
        return auth_error

    return jsonify({
        "status": "success",
        "message": "Admin API is working"
    }), 200