import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr
from werkzeug.security import generate_password_hash, check_password_hash
from jose import jwt, JWTError


# ============================================================
# PATH SETUP
# ============================================================

CURRENT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

BACKEND_ROOT = os.path.dirname(
    CURRENT_DIR
)

PROJECT_ROOT = os.path.dirname(
    BACKEND_ROOT
)

sys.path.insert(0, BACKEND_ROOT)
sys.path.insert(0, PROJECT_ROOT)


from database.database import get_db_connection


# ============================================================
# ROUTER
# ============================================================

auth_router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


# ============================================================
# JWT CONFIGURATION
# ============================================================

JWT_SECRET = os.getenv(
    "DOCURAG_JWT_SECRET",
    "docurag-jwt-development-secret-change-this"
)

JWT_ALGORITHM = "HS256"

JWT_EXPIRATION_MINUTES = 60


# ============================================================
# REQUEST MODELS
# ============================================================

class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ============================================================
# CREATE JWT TOKEN
# ============================================================

def create_access_token(user_id, email, role):

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=JWT_EXPIRATION_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


# ============================================================
# VERIFY JWT TOKEN
# ============================================================

def get_user_from_token(authorization):

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is required"
        )

    if not authorization.startswith("Bearer "):

        raise HTTPException(
            status_code=401,
            detail="Authorization must use Bearer token"
        )

    token = authorization.split(
        " ",
        1
    )[1].strip()

    if not token:

        raise HTTPException(
            status_code=401,
            detail="Access token is missing"
        )

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        user_id = payload.get("sub")

        if not user_id:

            raise HTTPException(
                status_code=401,
                detail="Invalid access token"
            )

        return payload

    except JWTError:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token"
        )


# ============================================================
# REGISTER
# ============================================================

@auth_router.post("/register")
def register(data: RegisterRequest):

    username = data.username.strip()
    email = str(data.email).strip().lower()
    password = data.password

    if not username:

        raise HTTPException(
            status_code=400,
            detail="Username cannot be empty"
        )

    if len(username) > 100:

        raise HTTPException(
            status_code=400,
            detail="Username is too long"
        )

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters"
        )

    connection = get_db_connection()

    try:

        # Check email
        existing_email = connection.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if existing_email:

            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        # Check username
        existing_username = connection.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if existing_username:

            raise HTTPException(
                status_code=409,
                detail="Username already exists"
            )

        password_hash = generate_password_hash(
            password
        )

        cursor = connection.execute(
            """
            INSERT INTO users (
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

        return {
            "status": "success",
            "message": "User registered successfully",
            "user_id": cursor.lastrowid,
            "username": username,
            "email": email
        }

    finally:

        connection.close()


# ============================================================
# LOGIN
# ============================================================

@auth_router.post("/login")
def login(data: LoginRequest):

    email = str(data.email).strip().lower()
    password = data.password

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

        if not user:

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        if not user["is_active"]:

            raise HTTPException(
                status_code=403,
                detail="Account is inactive"
            )

        if not check_password_hash(
            user["password_hash"],
            password
        ):

            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

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

        access_token = create_access_token(
            user["id"],
            user["email"],
            user["role"]
        )

        return {
            "status": "success",
            "message": "Login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRATION_MINUTES * 60,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"]
            }
        }

    finally:

        connection.close()


# ============================================================
# CURRENT USER
# ============================================================

@auth_router.get("/me")
def get_current_user(
    authorization: str = Header(default=None)
):

    payload = get_user_from_token(
        authorization
    )

    user_id = int(
        payload["sub"]
    )

    connection = get_db_connection()

    try:

        user = connection.execute(
            """
            SELECT
                id,
                username,
                email,
                role,
                is_active,
                created_at,
                last_login
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        if not user:

            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not user["is_active"]:

            raise HTTPException(
                status_code=403,
                detail="Account is inactive"
            )

        return {
            "status": "success",
            "user": dict(user)
        }

    finally:

        connection.close()


# ============================================================
# LOGOUT
# ============================================================

@auth_router.post("/logout")
def logout(
    authorization: str = Header(default=None)
):

    # Validate token before logout
    get_user_from_token(
        authorization
    )

    return {
        "status": "success",
        "message": (
            "Logout successful. "
            "Discard the access token on the client."
        )
    }