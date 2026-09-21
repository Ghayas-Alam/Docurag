import os
import sys
import hashlib
import uuid
import shutil

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Header,
    HTTPException
)

# ============================================================
# PATH SETUP
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_ROOT)

sys.path.insert(0, BACKEND_ROOT)
sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# PROJECT IMPORTS
# ============================================================
from database.database import get_db_connection
from services.document_processor import process_pdf
from services.image_file_processor import analyze_uploaded_image
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
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg"
}

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================
# AUTHENTICATION
# ============================================================
def get_authenticated_user(authorization: str):
    """
    Validate Bearer token and return authenticated user.
    """

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is required."
        )

    try:
        from api.auth_api import get_user_from_token

        user = get_user_from_token(authorization)

    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed: {str(e)}"
        )

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token."
        )

    return user


# ============================================================
# UPDATE DOCUMENT STATUS
# ============================================================
def update_document_status(
    document_id,
    status,
    error_message=None
):
    """
    Update processing status of a document.
    """

    connection = get_db_connection()

    try:
        connection.execute(
            """
            UPDATE documents
            SET
                processing_status = ?,
                error_message = ?,
                processed_at = CASE
                    WHEN ? = 'processed'
                    THEN CURRENT_TIMESTAMP
                    ELSE processed_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                error_message,
                status,
                document_id
            )
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ============================================================
# UPLOAD DOCUMENT
# ============================================================
@documents_router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    authorization: str = Header(None)
):
    """
    Upload and process PDF/image document.
    """

    # --------------------------------------------------------
    # Authenticate user
    # --------------------------------------------------------
    user = get_authenticated_user(authorization)

    user_id = user.get("sub") or user.get("id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid user information."
        )

    # --------------------------------------------------------
    # Validate filename
    # --------------------------------------------------------
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required."
        )

    original_filename = os.path.basename(
        file.filename
    )

    extension = os.path.splitext(
        original_filename
    )[1].lower()

    # --------------------------------------------------------
    # Validate extension
    # --------------------------------------------------------
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Allowed: PDF, PNG, JPG, JPEG."
            )
        )

    # --------------------------------------------------------
    # Read file
    # --------------------------------------------------------
    try:
        file_bytes = await file.read()

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read uploaded file: {str(e)}"
        )

    # --------------------------------------------------------
    # Validate size
    # --------------------------------------------------------
    file_size = len(file_bytes)

    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds 100 MB limit."
        )

    # --------------------------------------------------------
    # Calculate SHA256 hash
    # --------------------------------------------------------
    content_hash = hashlib.sha256(
        file_bytes
    ).hexdigest()

    # ========================================================
    # DATABASE CONNECTION
    # ========================================================
    connection = get_db_connection()

    try:

        # ----------------------------------------------------
        # Duplicate check
        # ----------------------------------------------------
        existing = connection.execute(
            """
            SELECT
                id,
                original_filename,
                processing_status
            FROM documents
            WHERE uploader_id = ?
              AND content_hash = ?
            LIMIT 1
            """,
            (
                user_id,
                content_hash
            )
        ).fetchone()

        if existing:

            return {
                "status": "duplicate",
                "message": "This document has already been uploaded.",
                "document_id": existing["id"],
                "filename": existing["original_filename"],
                "processing_status": existing["processing_status"]
            }

        # ----------------------------------------------------
        # Generate safe stored filename
        # ----------------------------------------------------
        stored_filename = (
             f"{uuid.uuid4().hex}_"
             f"{original_filename}"
        )  
        # Separate storage for PDFs and images 
        if extension == ".pdf":
            storage_dir = os.path.join(UPLOAD_DIR, "pdfs")
        else:
            storage_dir = os.path.join(UPLOAD_DIR, "images")

        os.makedirs(storage_dir, exist_ok=True)

        file_path = os.path.join(
        storage_dir,
        stored_filename
        )
        # ----------------------------------------------------
        # Save physical file
        # ----------------------------------------------------
        with open(file_path, "wb") as output_file:
            output_file.write(file_bytes)

        # ----------------------------------------------------
        # Detect file type
        # ----------------------------------------------------
        if extension == ".pdf":
            file_type = "pdf"
        else:
            file_type = "image"

        # ----------------------------------------------------
        # Insert document record
        # ----------------------------------------------------
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
                file_size,
                file_path,
                user_id,
                "uploaded",
                content_hash
            )
        )

        document_id = cursor.lastrowid

        connection.commit()

    except Exception as e:

        connection.rollback()

        # Remove physical file if DB insertion failed
        try:
            if "file_path" in locals() and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Could not save document: {str(e)}"
        )

    finally:
        connection.close()

    # ========================================================
    # PROCESS DOCUMENT
    # ========================================================
    try:

        # ----------------------------------------------------
        # PDF PROCESSING
        # ----------------------------------------------------
        if extension == ".pdf":

            processing_result = process_pdf(
                document_id
            )

        # ----------------------------------------------------
        # IMAGE PROCESSING
        # ----------------------------------------------------
        else:

            processing_result = analyze_uploaded_image(
                image_path=file_path,
                document_id=document_id,
                page_number=1,
                image_index=0
            )

        # ----------------------------------------------------
        # Validate processor result
        # ----------------------------------------------------
        if not processing_result:

            raise RuntimeError(
                "Document processor returned no result."
            )

        if processing_result.get("status") != "success":

            raise RuntimeError(
                processing_result.get(
                    "error",
                    "Document processing failed."
                )
            )

        # ====================================================
        # PROCESSING SUCCESS
        # ====================================================
        update_document_status(
            document_id=document_id,
            status="processed",
            error_message=None
        )

        # ----------------------------------------------------
        # Rebuild vector index
        # ----------------------------------------------------
        try:
            rebuild_index()
        except Exception as index_error:
            print(
                "Warning: Vector index rebuild failed:",
                index_error
            )

        return {
            "status": "success",
            "message": "File uploaded and processed successfully.",
            "document_id": document_id,
            "filename": original_filename,
            "file_type": file_type,
            "processing_status": "processed",
            "processing_result": processing_result
        }

    # ========================================================
    # PROCESSING FAILURE
    # ========================================================
    except Exception as processing_error:

        error_message = str(
            processing_error
        )

        print(
            f"Document processing failed "
            f"for document {document_id}: "
            f"{error_message}"
        )

        try:
            update_document_status(
                document_id=document_id,
                status="failed",
                error_message=error_message
            )
        except Exception as status_error:
            print(
                "Could not update failed status:",
                status_error
            )

        return {
            "status": "failed",
            "message": (
                "File uploaded but processing failed."
            ),
            "document_id": document_id,
            "filename": original_filename,
            "processing_status": "failed",
            "error": error_message
        }


# ============================================================
# LIST USER DOCUMENTS
# ============================================================
@documents_router.get("")
async def list_documents(
    authorization: str = Header(None)
):
    """
    Return all documents uploaded by current user.
    """

    user = get_authenticated_user(authorization)

    user_id = user.get("sub") or user.get("id")

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
            (user_id,)
        ).fetchall()

        documents = [
            dict(row)
            for row in rows
        ]

        return {
            "status": "success",
            "documents": documents
        }

    finally:
        connection.close()


# ============================================================
# GET DOCUMENT DETAILS
# ============================================================
@documents_router.get("/{document_id}")
async def get_document(
    document_id: int,
    authorization: str = Header(None)
):
    """
    Get details of one document.
    """

    user = get_authenticated_user(authorization)

    user_id = user.get("sub") or user.get("id")

    connection = get_db_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                filename,
                original_filename,
                file_type,
                file_size,
                file_path,
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

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Document not found."
            )

        return {
            "status": "success",
            "document": dict(row)
        }

    finally:
        connection.close()


# ============================================================
# DOCUMENT STATUS
# ============================================================
@documents_router.get("/{document_id}/status")
async def get_document_status(
    document_id: int,
    authorization: str = Header(None)
):
    """
    Get processing status of a document.
    """

    user = get_authenticated_user(authorization)

    user_id = user.get("sub") or user.get("id")

    connection = get_db_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                original_filename,
                processing_status,
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

        if not row:

            raise HTTPException(
                status_code=404,
                detail="Document not found."
            )

        return {
            "status": "success",
            "document": dict(row)
        }

    finally:
        connection.close()


# ============================================================
# DELETE DOCUMENT
# ============================================================
@documents_router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    authorization: str = Header(None)
):
    """
    Delete a user's document and associated data.
    """

    user = get_authenticated_user(authorization)

    user_id = user.get("sub") or user.get("id")

    connection = get_db_connection()

    try:

        # ----------------------------------------------------
        # Find document
        # ----------------------------------------------------
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
                detail="Document not found."
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
            (document_id,)
        )

        # ----------------------------------------------------
        # Delete image analysis
        # ----------------------------------------------------
        connection.execute(
            """
            DELETE FROM image_analysis
            WHERE document_id = ?
            """,
            (document_id,)
        )

        # ----------------------------------------------------
        # Delete chunks
        # ----------------------------------------------------
        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = ?
            """,
            (document_id,)
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

    except HTTPException:
        connection.rollback()
        raise

    except Exception as e:

        connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Could not delete document: {str(e)}"
        )

    finally:
        connection.close()

    # ========================================================
    # DELETE PHYSICAL FILE
    # ========================================================
    try:

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:

        print(
            "Warning: Could not delete physical file:",
            e
        )

    # ========================================================
    # DELETE EXTRACTED IMAGES FOLDER
    # ========================================================
    try:

        extracted_images_dir = os.path.join(
            UPLOAD_DIR,
            f"extracted_images_{document_id}"
        )

        if os.path.exists(extracted_images_dir):

            shutil.rmtree(
                extracted_images_dir,
                ignore_errors=True
            )

    except Exception as e:

        print(
            "Warning: Could not delete extracted images:",
            e
        )

    # ========================================================
    # REBUILD VECTOR INDEX
    # ========================================================
    try:

        rebuild_index()

    except Exception as e:

        print(
            "Warning: Could not rebuild vector index:",
            e
        )

    return {
        "status": "success",
        "message": "Document deleted successfully.",
        "document_id": document_id
    }