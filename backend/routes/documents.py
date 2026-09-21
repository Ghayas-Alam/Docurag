import os
import sys
import uuid
import hashlib
import shutil

from flask import Blueprint, request, jsonify, session
from werkzeug.utils import secure_filename


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

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, BACKEND_ROOT)


# ============================================================
# DATABASE
# ============================================================

from database.database import get_db_connection


# ============================================================
# PDF PROCESSOR
# ============================================================

from services.document_processor import process_pdf


# ============================================================
# VECTOR STORE
# ============================================================

from services.vector_store import rebuild_index


# ============================================================
# IMAGE PROCESSOR
# ============================================================

from services.image_file_processor import analyze_uploaded_image


# ============================================================
# BLUEPRINT
# ============================================================

documents_bp = Blueprint(
    "documents",
    __name__
)


# ============================================================
# CONFIGURATION
# ============================================================

UPLOAD_FOLDER = os.path.join(
    PROJECT_ROOT,
    "uploads"
)

EXTRACTED_IMAGES_FOLDER = os.path.join(
    PROJECT_ROOT,
    "extracted_images"
)

ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg"
}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

os.makedirs(
    EXTRACTED_IMAGES_FOLDER,
    exist_ok=True
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def allowed_file(filename):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(
        ".",
        1
    )[1].lower()

    return extension in ALLOWED_EXTENSIONS


def get_extension(filename):

    return filename.rsplit(
        ".",
        1
    )[1].lower()


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

            sha256.update(data)

    return sha256.hexdigest()


def get_current_user_id():

    return session.get(
        "user_id"
    )


def document_belongs_to_user(
    connection,
    document_id,
    user_id
):

    document = connection.execute(
        """
        SELECT *
        FROM documents
        WHERE id = ?
        AND uploader_id = ?
        """,
        (
            document_id,
            user_id
        )
    ).fetchone()

    return document


# ============================================================
# UPLOAD DOCUMENT / IMAGE
# ============================================================

@documents_bp.route(
    "/upload",
    methods=["POST"]
)
def upload_document():

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    # --------------------------------------------------------
    # Check file
    # --------------------------------------------------------

    if "file" not in request.files:

        return jsonify({
            "status": "error",
            "message": "No file provided"
        }), 400


    file = request.files["file"]


    if not file or not file.filename:

        return jsonify({
            "status": "error",
            "message": "No file selected"
        }), 400


    original_filename = secure_filename(
        file.filename
    )


    if not original_filename:

        return jsonify({
            "status": "error",
            "message": "Invalid filename"
        }), 400


    # --------------------------------------------------------
    # Check extension
    # --------------------------------------------------------

    if not allowed_file(
        original_filename
    ):

        return jsonify({
            "status": "error",
            "message": (
                "Unsupported file type. "
                "Allowed types: PDF, PNG, JPG, JPEG"
            )
        }), 400


    extension = get_extension(
        original_filename
    )


    # --------------------------------------------------------
    # Generate unique filename
    # --------------------------------------------------------

    unique_filename = (
        str(uuid.uuid4()).replace("-", "")
        + "_"
        + original_filename
    )


    final_path = os.path.join(
        UPLOAD_FOLDER,
        unique_filename
    )


    # --------------------------------------------------------
    # Save temporary file first
    # --------------------------------------------------------

    temp_filename = (
        "temp_"
        + str(uuid.uuid4())
        + "_"
        + original_filename
    )

    temp_path = os.path.join(
        UPLOAD_FOLDER,
        temp_filename
    )


    try:

        file.save(
            temp_path
        )

        file_size = os.path.getsize(
            temp_path
        )


        # ----------------------------------------------------
        # Empty file
        # ----------------------------------------------------

        if file_size == 0:

            os.remove(
                temp_path
            )

            return jsonify({
                "status": "error",
                "message": "Uploaded file is empty"
            }), 400


        # ----------------------------------------------------
        # File size validation
        # ----------------------------------------------------

        if file_size > MAX_FILE_SIZE:

            os.remove(
                temp_path
            )

            return jsonify({
                "status": "error",
                "message": (
                    "File size exceeds the 100 MB limit"
                )
            }), 400


        # ----------------------------------------------------
        # Calculate SHA256
        # ----------------------------------------------------

        content_hash = calculate_file_hash(
            temp_path
        )


        # ----------------------------------------------------
        # Duplicate check
        # ----------------------------------------------------

        connection = get_db_connection()

        try:

            duplicate = connection.execute(
                """
                SELECT id, original_filename
                FROM documents
                WHERE uploader_id = ?
                AND content_hash = ?
                """,
                (
                    user_id,
                    content_hash
                )
            ).fetchone()

        finally:

            connection.close()


        if duplicate:

            os.remove(
                temp_path
            )

            return jsonify({
                "status": "error",
                "message": "Duplicate document already exists",
                "existing_document_id": duplicate["id"],
                "existing_filename": duplicate[
                    "original_filename"
                ]
            }), 409


        # ----------------------------------------------------
        # Move temporary file to final location
        # ----------------------------------------------------

        os.replace(
            temp_path,
            final_path
        )


        # ----------------------------------------------------
        # Insert document into database
        # ----------------------------------------------------

        connection = get_db_connection()

        try:

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
                    unique_filename,
                    original_filename,
                    extension,
                    file_size,
                    final_path,
                    user_id,
                    "uploaded",
                    content_hash
                )
            )

            document_id = cursor.lastrowid

            connection.commit()

        except Exception:

            connection.rollback()
            raise

        finally:

            connection.close()


        # ====================================================
        # PDF PROCESSING
        # ====================================================

        if extension == "pdf":

            try:

                processing_result = process_pdf(
                    document_id
                )

                connection = get_db_connection()

                try:

                    document = connection.execute(
                        """
                        SELECT *
                        FROM documents
                        WHERE id = ?
                        AND uploader_id = ?
                        """,
                        (
                            document_id,
                            user_id
                        )
                    ).fetchone()

                finally:

                    connection.close()


                return jsonify({
                    "status": "success",
                    "message": "Document uploaded successfully",
                    "document": dict(document),
                    "processing": processing_result
                }), 201


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


                return jsonify({
                    "status": "success",
                    "message": (
                        "Document uploaded, "
                        "but processing failed"
                    ),
                    "document_id": document_id,
                    "processing": {
                        "status": "failed",
                        "message": str(error)
                    }
                }), 201


        # ====================================================
        # STANDALONE IMAGE PROCESSING
        # ====================================================

        if extension in {
            "png",
            "jpg",
            "jpeg"
        }:

            try:

                # ------------------------------------------------
                # Update status
                # ------------------------------------------------

                connection = get_db_connection()

                try:

                    connection.execute(
                        """
                        UPDATE documents
                        SET processing_status = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            "processing",
                            document_id
                        )
                    )

                    connection.commit()

                finally:

                    connection.close()


                # ------------------------------------------------
                # Gemini image analysis
                # ------------------------------------------------

                analysis_result = analyze_uploaded_image(
                    final_path,
                    document_id
                )


                # ------------------------------------------------
                # Update document status
                # ------------------------------------------------

                connection = get_db_connection()

                try:

                    connection.execute(
                        """
                        UPDATE documents
                        SET processing_status = ?,
                            error_message = ?,
                            processed_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP,
                            page_count = ?
                        WHERE id = ?
                        """,
                        (
                            "processed",
                            None,
                            1,
                            document_id
                        )
                    )

                    connection.commit()

                finally:

                    connection.close()


                # ------------------------------------------------
                # Get updated document
                # ------------------------------------------------

                connection = get_db_connection()

                try:

                    document = connection.execute(
                        """
                        SELECT *
                        FROM documents
                        WHERE id = ?
                        AND uploader_id = ?
                        """,
                        (
                            document_id,
                            user_id
                        )
                    ).fetchone()

                finally:

                    connection.close()


                return jsonify({
                    "status": "success",
                    "message": (
                        "Image uploaded and analyzed successfully"
                    ),
                    "document": dict(document),
                    "processing": analysis_result
                }), 201


            except Exception as error:

                # ----------------------------------------------
                # Keep uploaded image but mark processing failed
                # ----------------------------------------------

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


                return jsonify({
                    "status": "success",
                    "message": (
                        "Image uploaded, "
                        "but image analysis failed"
                    ),
                    "document_id": document_id,
                    "processing": {
                        "status": "failed",
                        "message": str(error)
                    }
                }), 201


    except Exception as error:

        # ----------------------------------------------------
        # Cleanup temporary/final file if necessary
        # ----------------------------------------------------

        if os.path.exists(
            temp_path
        ):

            try:
                os.remove(
                    temp_path
                )
            except Exception:
                pass


        return jsonify({
            "status": "error",
            "message": (
                "Failed to upload document"
            ),
            "error": str(error)
        }), 500


# ============================================================
# LIST DOCUMENTS
# ============================================================

@documents_bp.route(
    "",
    methods=["GET"]
)
def list_documents():

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    connection = get_db_connection()

    try:

        documents = connection.execute(
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
            ORDER BY upload_date DESC
            """,
            (
                user_id,
            )
        ).fetchall()

    finally:

        connection.close()


    return jsonify({
        "status": "success",
        "count": len(documents),
        "documents": [
            dict(document)
            for document in documents
        ]
    }), 200


# ============================================================
# DOCUMENT DETAIL
# ============================================================

@documents_bp.route(
    "/<int:document_id>",
    methods=["GET"]
)
def get_document(
    document_id
):

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    connection = get_db_connection()

    try:

        document = document_belongs_to_user(
            connection,
            document_id,
            user_id
        )

    finally:

        connection.close()


    if not document:

        return jsonify({
            "status": "error",
            "message": "Document not found"
        }), 404


    return jsonify({
        "status": "success",
        "document": dict(document)
    }), 200


# ============================================================
# PROCESSING STATUS
# ============================================================

@documents_bp.route(
    "/<int:document_id>/status",
    methods=["GET"]
)
def document_status(
    document_id
):

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    connection = get_db_connection()

    try:

        document = connection.execute(
            """
            SELECT
                id,
                original_filename,
                file_type,
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

    finally:

        connection.close()


    if not document:

        return jsonify({
            "status": "error",
            "message": "Document not found"
        }), 404


    return jsonify({
        "status": "success",
        "document": dict(document)
    }), 200


# ============================================================
# DELETE DOCUMENT
# ============================================================

@documents_bp.route(
    "/<int:document_id>",
    methods=["DELETE"]
)
def delete_document(
    document_id
):

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401


    connection = get_db_connection()

    try:

        document = document_belongs_to_user(
            connection,
            document_id,
            user_id
        )

    finally:

        connection.close()


    if not document:

        return jsonify({
            "status": "error",
            "message": "Document not found"
        }), 404


    file_path = document["file_path"]


    # --------------------------------------------------------
    # Delete database records
    # --------------------------------------------------------

    connection = get_db_connection()

    try:

        connection.execute(
            """
            DELETE FROM query_sources
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

        connection.execute(
            """
            DELETE FROM image_analysis
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = ?
            """,
            (
                document_id,
            )
        )

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

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


    # --------------------------------------------------------
    # Delete uploaded file
    # --------------------------------------------------------

    if file_path and os.path.exists(
        file_path
    ):

        try:

            os.remove(
                file_path
            )

        except Exception:
            pass


    # --------------------------------------------------------
    # Delete extracted images
    # --------------------------------------------------------

    document_images_folder = os.path.join(
        EXTRACTED_IMAGES_FOLDER,
        str(document_id)
    )

    if os.path.exists(
        document_images_folder
    ):

        try:

            shutil.rmtree(
                document_images_folder
            )

        except Exception:
            pass


    # --------------------------------------------------------
    # Rebuild FAISS index
    # --------------------------------------------------------

    try:

        vector_result = rebuild_index()

    except Exception as error:

        vector_result = {
            "status": "error",
            "message": str(error)
        }


    return jsonify({
        "status": "success",
        "message": "Document deleted successfully",
        "document_id": document_id,
        "vector_index": vector_result
    }), 200