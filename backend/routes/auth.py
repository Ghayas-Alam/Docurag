from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import sys
import os


# Project root
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

sys.path.append(PROJECT_ROOT)

from database.database import get_db_connection


auth_bp = Blueprint("auth", __name__)


# =========================================================
# REGISTER
# =========================================================

@auth_bp.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is required"
        }), 400

    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    # Required fields
    if not username or not email or not password:
        return jsonify({
            "status": "error",
            "message": "Username, email and password are required"
        }), 400

    # Username validation
    if len(username) < 3:
        return jsonify({
            "status": "error",
            "message": "Username must be at least 3 characters"
        }), 400

    # Basic email validation
    if "@" not in email or "." not in email:
        return jsonify({
            "status": "error",
            "message": "Invalid email address"
        }), 400

    # Password validation
    if len(password) < 8:
        return jsonify({
            "status": "error",
            "message": "Password must be at least 8 characters"
        }), 400

    connection = get_db_connection()

    try:

        # Check existing username/email
        existing_user = connection.execute(
            """
            SELECT id
            FROM users
            WHERE username = ? OR email = ?
            """,
            (username, email)
        ).fetchone()

        if existing_user:
            return jsonify({
                "status": "error",
                "message": "Username or email already exists"
            }), 409

        # Hash password
        password_hash = generate_password_hash(password)

        # Insert user
        cursor = connection.execute(
            """
            INSERT INTO users
            (
                username,
                email,
                password_hash,
                role,
                is_active
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                username,
                email,
                password_hash,
                "user",
                1
            )
        )

        connection.commit()

        return jsonify({
            "status": "success",
            "message": "User registered successfully",
            "user_id": cursor.lastrowid
        }), 201

    except Exception:
        connection.rollback()

        return jsonify({
            "status": "error",
            "message": "Registration failed"
        }), 500

    finally:
        connection.close()


# =========================================================
# LOGIN
# =========================================================

@auth_bp.route("/login", methods=["POST"])
def login():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "status": "error",
            "message": "Request body is required"
        }), 400

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({
            "status": "error",
            "message": "Email and password are required"
        }), 400

    connection = get_db_connection()

    try:

        user = connection.execute(
            """
            SELECT
                id,
                username,
                email,
                password_hash,
                role,
                is_active
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        # Same message for wrong email/password
        if not user:
            return jsonify({
                "status": "error",
                "message": "Invalid email or password"
            }), 401

        # Check account status
        if not user["is_active"]:
            return jsonify({
                "status": "error",
                "message": "Account is inactive"
            }), 403

        # Verify password
        if not check_password_hash(
            user["password_hash"],
            password
        ):
            return jsonify({
                "status": "error",
                "message": "Invalid email or password"
            }), 401

        # Create login session
        session.clear()

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

        # Update last login
        connection.execute(
            """
            UPDATE users
            SET last_login = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user["id"],)
        )

        connection.commit()

        return jsonify({
            "status": "success",
            "message": "Login successful",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"]
            }
        }), 200

    except Exception:

        connection.rollback()

        return jsonify({
            "status": "error",
            "message": "Login failed"
        }), 500

    finally:
        connection.close()


# =========================================================
# CURRENT USER
# =========================================================

@auth_bp.route("/me", methods=["GET"])
def current_user():

    # Check session
    if "user_id" not in session:
        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401

    connection = get_db_connection()

    try:

        user = connection.execute(
            """
            SELECT
                id,
                username,
                email,
                role,
                is_active
            FROM users
            WHERE id = ?
            """,
            (session["user_id"],)
        ).fetchone()

        if not user:
            session.clear()

            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 401

        if not user["is_active"]:
            session.clear()

            return jsonify({
                "status": "error",
                "message": "Account is inactive"
            }), 403

        return jsonify({
            "status": "success",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"]
            }
        }), 200

    finally:
        connection.close()


# =========================================================
# LOGOUT
# =========================================================

@auth_bp.route("/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "status": "success",
        "message": "Logout successful"
    }), 200