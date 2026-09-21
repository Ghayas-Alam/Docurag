import sys
import os
import getpass

# =========================
# Project Root
# =========================

PROJECT_ROOT = os.path.dirname(
    os.path.abspath(__file__)
)

sys.path.append(PROJECT_ROOT)


# =========================
# Imports
# =========================

from werkzeug.security import generate_password_hash
from database.database import get_db_connection


# =========================
# Create Admin
# =========================

def create_admin():

    print("\n==============================")
    print("      DocuRAG Admin Setup")
    print("==============================\n")

    username = input("Admin username: ").strip()
    email = input("Admin email: ").strip()

    password = getpass.getpass("Admin password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if not username or not email or not password:
        print("\nError: All fields are required.")
        return

    if password != confirm_password:
        print("\nError: Passwords do not match.")
        return

    # Same password requirements as normal signup
    if len(password) < 8:
        print("\nError: Password must contain at least 8 characters.")
        return

    if not any(c.isupper() for c in password):
        print("\nError: Password must contain an uppercase letter.")
        return

    if not any(c.islower() for c in password):
        print("\nError: Password must contain a lowercase letter.")
        return

    if not any(c.isdigit() for c in password):
        print("\nError: Password must contain a number.")
        return

    if not any(not c.isalnum() for c in password):
        print("\nError: Password must contain a special character.")
        return

    connection = get_db_connection()

    try:

        existing_user = connection.execute(
            """
            SELECT id, username, email
            FROM users
            WHERE username = ? OR email = ?
            """,
            (username, email)
        ).fetchone()

        if existing_user:

            print("\nError: Username or email already exists.")
            return

        password_hash = generate_password_hash(password)

        connection.execute(
            """
            INSERT INTO users
            (
                username,
                email,
                password_hash,
                role,
                is_active
            )
            VALUES (?, ?, ?, 'admin', 1)
            """,
            (
                username,
                email,
                password_hash
            )
        )

        connection.commit()

        print("\n==============================")
        print("Admin account created successfully!")
        print("==============================")
        print(f"Username : {username}")
        print(f"Email    : {email}")
        print("Role     : admin")
        print("==============================\n")

    except Exception as e:

        connection.rollback()

        print("\nError creating admin:")
        print(e)

    finally:

        connection.close()


# =========================
# Run
# =========================

if __name__ == "__main__":
    create_admin()