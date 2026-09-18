import os
import sys
import hashlib
import uuid
import shutil

from fastapi import APIRouter, UploadFile, File, Header, HTTPException


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


# ============================================================
# IMPORTS
# ============================================================

from database.database import get_db_connection

from services.document_processor import process_pdf

from services.image_file_processor import (
    analyze_uploaded_image
)

from services.vector_store import rebuild_index


# ============================================================
# ROUTER
# ============================================================

documents_router = APIRouter(
    prefix="/api/documents",
    tags=["Documents"]
)


# ============================================================
# CONFIGURATION
# ============================================================

UPLOAD_FOLDER = os.path.join(
    PROJECT_ROOT,
    "uploads"
)

MAX_FILE_SIZE = 100 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg"
}


# ============================================================
# CREATE UPLOAD FOLDER
# ============================================================

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)


# ============================================================
# JWT AUTH HELPER
# ============================================================

from api.auth_api import get_user_from_token


def get_authenticated_user(
    authorization
):

    payload = get_user_from_token(
        authorization
    )

    try:
        user_id = int(
            payload["sub"]
        )
    except Exception:

        raise HTTPException(
            status_code=401,
            detail="Invalid user information in token"
        )

    return user_id


# ============================================================
# FILE EXTENSION
# ============================================================

def get_extension(filename):

    if not filename:
        return ""

    filename = filename.lower()

    if "." not in filename:
        return ""

    return filename.rsplit(
        ".",
        1
    )[1]


# ============================================================
# SHA256 HASH
# ============================================================

def calculate_file_hash(file_path):

    sha256 = hashlib.sha256()

    with open(
        file_path,
        "rb"
    ) as file:

        while True:

            data = file.read(
                1024 * 1024
            )

            if not data:
                break

            sha256.update(
                data
            )

    return sha256.hexdigest()


# ============================================================
# UPLOAD DOCUMENT / IMAGE
# ============================================================

@documents_router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    authorization: str = Header(default=None)
):

    user_id = get_authenticated_user(
        authorization
    )

    # --------------------------------------------------------
    # Validate filename
    # --------------------------------------------------------

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="Filename is required"
        )

    original_filename = file.filename.strip()

    extension = get_extension(
        original_filename
    )

    if extension not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Allowed: PDF, PNG, JPG, JPEG"
            )
        )

    # --------------------------------------------------------
    # Read file
    # --------------------------------------------------------

    file_data = await file.read()

    if not file_data:

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    if len(file_data) > MAX_FILE_SIZE:

        raise HTTPException(
            status_code=413,
            detail="File size exceeds 100 MB limit"
        )

    # --------------------------------------------------------
    # Calculate hash
    # --------------------------------------------------------

    content_hash = hashlib.sha256(
        file_data
    ).hexdigest()

    connection = get_db_connection()

    try:

        # ----------------------------------------------------
        # Duplicate check
        # ----------------------------------------------------

        existing = connection.execute(
            """
            SELECT
                id,
                filename,
                processing_status
            FROM documents
            WHERE uploader_id = ?
            AND content_hash = ?
            """,
            (
                user_id,
                content_hash
            )
        ).fetchone()

        if existing:

            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Duplicate file already uploaded",
                    "document_id": existing["id"],
                    "filename": existing["filename"],
                    "processing_status": existing["processing_status"]
                }
            )

        # ----------------------------------------------------
        # Generate safe stored filename
        # ----------------------------------------------------

        stored_filename = (
            f"{uuid.uuid4().hex}_"
            f"{os.path.basename(original_filename)}"
        )

        file_path = os.path.join(
            UPLOAD_FOLDER,
            stored_filename
        )

        # ----------------------------------------------------
        # Save file
        # ----------------------------------------------------

        with open(
            file_path,
            "wb"
        ) as output_file:

            output_file.write(
                file_data
            )

        # ----------------------------------------------------
        # Insert document
        # ----------------------------------------------------

        file_type = extension

        cursor = connection.execute(
            """
            INSERT INTO documents (
                filename,
                original_filename,
                file_type,
                file_size,
                file_path,
                uploader_id,
                processing_status,
                content_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stored_filename,
                original_filename,
                file_type,
                len(file_data),
                file_path,
                user_id,
                "uploaded",
                content_hash
            )
        )

        document_id = cursor.lastrowid

        connection.commit()

    except HTTPException:
        raise

    except Exception as error:

        connection.rollback()

        # Remove file if DB insertion failed
        if os.path.exists(file_path):

            os.remove(
                file_path
            )

        raise HTTPException(
            status_code=500,
            detail=f"Failed to save document: {str(error)}"
        )

    finally:

        connection.close()

    # ========================================================
    # PROCESS FILE
    # ========================================================

    processing_result = None

    try:

        if extension == "pdf":

            processing_result = process_pdf(
                document_id
            )

        else:

            processing_result = (
                analyze_uploaded_image(
                    file_path,
                    document_id
                )
            )

        return {
            "status": "success",
            "message": "File uploaded and processed successfully",
            "document_id": document_id,
            "filename": original_filename,
            "file_type": file_type,
            "file_size": len(file_data),
            "processing": processing_result
        }

    except Exception as error:

        connection = get_db_connection()

        try:

            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?,
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    "failed",
                    str(error),
                    document_id
                )
            )

            connection.commit()

        finally:

            connection.close()

        return {
            "status": "success",
            "message": "File uploaded but processing failed",
            "document_id": document_id,
            "filename": original_filename,
            "file_type": file_type,
            "processing": {
                "status": "failed",
                "error": str(error)
            }
        }


# ============================================================
# LIST DOCUMENTS
# ============================================================

@documents_router.get("")
def list_documents(
    authorization: str = Header(default=None)
):

    user_id = get_authenticated_user(
        authorization
    )

    connection = get_db_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                filename,
                original_filename,
                file_type,
                file_size,
                upload_date,
                uploader_id,
                processing_status,
                page_count,
                error_message,
                processed_at,
                created_at,
                updated_at
            FROM documents
            WHERE uploader_id = ?
            ORDER BY created_at DESC
            """,
            (
                user_id,
            )
        ).fetchall()

        return {
            "status": "success",
            "count": len(rows),
            "documents": [
                dict(row)
                for row in rows
            ]
        }

    finally:

        connection.close()


# ============================================================
# DOCUMENT DETAIL
# ============================================================

@documents_router.get("/{document_id}")
def get_document(
    document_id: int,
    authorization: str = Header(default=None)
):

    user_id = get_authenticated_user(
        authorization
    )

    connection = get_db_connection()

    try:

        document = connection.execute(
            """
            SELECT
                id,
                filename,
                original_filename,
                file_type,
                file_size,
                upload_date,
                uploader_id,
                processing_status,
                page_count,
                error_message,
                processed_at,
                created_at,
                updated_at
            FROM documents
            WHERE id = ?
            AND uploader_id = ?
            """,
            (
                document_id,
                user_id
            )
        ).fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        chunk_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM document_chunks
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        ).fetchone()["count"]

        image_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM image_analysis
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        ).fetchone()["count"]

        result = dict(
            document
        )

        result["chunk_count"] = chunk_count
        result["image_count"] = image_count

        return {
            "status": "success",
            "document": result
        }

    finally:

        connection.close()


# ============================================================
# PROCESSING STATUS
# ============================================================

@documents_router.get("/{document_id}/status")
def document_status(
    document_id: int,
    authorization: str = Header(default=None)
):

    user_id = get_authenticated_user(
        authorization
    )

    connection = get_db_connection()

    try:

        document = connection.execute(
            """
            SELECT
                id,
                original_filename,
                processing_status,
                page_count,
                error_message,
                processed_at
            FROM documents
            WHERE id = ?
            AND uploader_id = ?
            """,
            (
                document_id,
                user_id
            )
        ).fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        return {
            "status": "success",
            "document": dict(document)
        }

    finally:

        connection.close()


# ============================================================
# DELETE DOCUMENT
# ============================================================

@documents_router.delete("/{document_id}")
def delete_document(
    document_id: int,
    authorization: str = Header(default=None)
):

    user_id = get_authenticated_user(
        authorization
    )

    connection = get_db_connection()

    try:

        document = connection.execute(
            """
            SELECT
                id,
                file_path,
                original_filename
            FROM documents
            WHERE id = ?
            AND uploader_id = ?
            """,
            (
                document_id,
                user_id
            )
        ).fetchone()

        if not document:

            raise HTTPException(
                status_code=404,
                detail="Document not found"
            )

        file_path = document["file_path"]

        # ----------------------------------------------------
        # Delete query sources
        # ----------------------------------------------------

        connection.execute(
            """
            DELETE FROM query_sources
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

        # ----------------------------------------------------
        # Delete image analysis
        # ----------------------------------------------------

        connection.execute(
            """
            DELETE FROM image_analysis
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

        # ----------------------------------------------------
        # Delete chunks
        # ----------------------------------------------------

        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

        # ----------------------------------------------------
        # Delete document
        # ----------------------------------------------------

        connection.execute(
            """
            DELETE FROM documents
            WHERE id = ?
            AND uploader_id = ?
            """,
            (
                document_id,
                user_id
            )
        )

        connection.commit()

    finally:

        connection.close()

    # --------------------------------------------------------
    # Delete physical file
    # --------------------------------------------------------

    if file_path and os.path.exists(
        file_path
    ):

        try:

            os.remove(
                file_path
            )

        except Exception as error:

            print(
                "File deletion error:",
                error
            )

    # --------------------------------------------------------
    # Delete extracted images
    # --------------------------------------------------------

    extracted_folder = os.path.join(
        PROJECT_ROOT,
        "extracted_images",
        str(document_id)
    )

    if os.path.exists(
        extracted_folder
    ):

        try:

            shutil.rmtree(
                extracted_folder
            )

        except Exception as error:

            print(
                "Extracted image deletion error:",
                error
            )

    # --------------------------------------------------------
    # Rebuild FAISS
    # --------------------------------------------------------

    vector_index_result = None

    try:

        vector_index_result = rebuild_index()

    except Exception as error:

        vector_index_result = {
            "status": "failed",
            "error": str(error)
        }

    return {
        "status": "success",
        "message": "Document deleted successfully",
        "document_id": document_id,
        "vector_index": vector_index_result
    }