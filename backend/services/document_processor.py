import os
import sys

# ============================================================
# PROJECT PATH SETUP
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_ROOT)

sys.path.insert(0, BACKEND_ROOT)
sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# IMPORTS
# ============================================================

import pymupdf

from database.database import get_db_connection
from services.vector_store import rebuild_index


# ============================================================
# CHUNKING CONFIGURATION
# ============================================================

CHUNK_SIZE = 3000
CHUNK_OVERLAP = 1000


# ============================================================
# CREATE TEXT CHUNKS
# ============================================================

def create_chunks(
    text,
    chunk_size=CHUNK_SIZE,
    overlap=CHUNK_OVERLAP
):
    """
    Split text into overlapping chunks.

    Example:
    chunk size = 3000 characters
    overlap = 1000 characters
    """

    if not text:
        return []

    chunks = []

    step = chunk_size - overlap

    if step <= 0:
        raise ValueError(
            "Chunk overlap must be smaller than chunk size."
        )

    for start in range(
        0,
        len(text),
        step
    ):

        chunk = text[
            start:start + chunk_size
        ]

        if not chunk:
            break

        if chunk.strip():
            chunks.append(chunk)

    return chunks


# ============================================================
# PROCESS PDF
# ============================================================

def process_pdf(document_id):

    connection = None
    pdf = None

    try:

        print()
        print("=" * 60)
        print("PDF PROCESSING")
        print("=" * 60)
        print(f"Document ID: {document_id}")

        # ----------------------------------------------------
        # Get document information
        # ----------------------------------------------------

        connection = get_db_connection()

        document = connection.execute(
            """
            SELECT
                id,
                original_filename,
                file_path,
                file_type
            FROM documents
            WHERE id = ?
            """,
            (document_id,)
        ).fetchone()

        if not document:

            return {
                "status": "error",
                "document_id": document_id,
                "message": "Document not found."
            }

        document = dict(document)

        file_path = document["file_path"]
        file_type = (
            document["file_type"] or ""
        ).lower()

        # ----------------------------------------------------
        # Validate file type
        # ----------------------------------------------------

        if file_type != "pdf":

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    "Only PDF processing is currently supported.",
                    document_id
                )
            )

            connection.commit()

            return {
                "status": "error",
                "document_id": document_id,
                "message": "Only PDF processing is currently supported."
            }

        # ----------------------------------------------------
        # Validate file path
        # ----------------------------------------------------

        if not file_path:

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    "Document file path is missing.",
                    document_id
                )
            )

            connection.commit()

            return {
                "status": "error",
                "document_id": document_id,
                "message": "Document file path is missing."
            }

        if not os.path.exists(file_path):

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    "Document file was not found on disk.",
                    document_id
                )
            )

            connection.commit()

            return {
                "status": "error",
                "document_id": document_id,
                "message": "Document file was not found on disk."
            }

        # ----------------------------------------------------
        # Check empty file
        # ----------------------------------------------------

        file_size = os.path.getsize(file_path)

        if file_size == 0:

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    "Document file is empty.",
                    document_id
                )
            )

            connection.commit()

            return {
                "status": "error",
                "document_id": document_id,
                "message": "Document file is empty."
            }

        # ----------------------------------------------------
        # Mark as processing
        # ----------------------------------------------------

        connection.execute(
            """
            UPDATE documents
            SET
                processing_status = ?,
                error_message = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                "processing",
                document_id
            )
        )

        connection.commit()

        # ----------------------------------------------------
        # Open PDF
        # ----------------------------------------------------

        print("Opening PDF...")

        try:

            pdf = pymupdf.open(file_path)

        except Exception as error:

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    f"Could not open PDF: {str(error)}",
                    document_id
                )
            )

            connection.commit()

            return {
                "status": "error",
                "document_id": document_id,
                "message": f"Could not open PDF: {str(error)}"
            }

        # ----------------------------------------------------
        # PDF statistics
        # ----------------------------------------------------

        total_pages = len(pdf)

        text_pages = 0
        scanned_pages = 0
        empty_pages = 0
        chunks_created = 0

        print(f"Total pages: {total_pages}")

        # ----------------------------------------------------
        # Delete old chunks
        #
        # Important when a document is reprocessed.
        # ----------------------------------------------------

        connection.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = ?
            """,
            (document_id,)
        )

        connection.commit()

        # ----------------------------------------------------
        # Process every page
        # ----------------------------------------------------

        for page_number in range(total_pages):

            page = pdf[page_number]

            # -----------------------------------------------
            # Extract text
            # -----------------------------------------------

            text = page.get_text("text")

            text = text.strip() if text else ""

            # -----------------------------------------------
            # Check images on page
            # -----------------------------------------------

            images = page.get_images(
                full=True
            )

            # -----------------------------------------------
            # Page classification
            # -----------------------------------------------

            if text:

                text_pages += 1

            elif images:

                scanned_pages += 1

            else:

                empty_pages += 1

            # -----------------------------------------------
            # No text
            # -----------------------------------------------

            if not text:
                continue

            # -----------------------------------------------
            # Create chunks
            # -----------------------------------------------

            chunks = create_chunks(text)

            # -----------------------------------------------
            # Store chunks
            # -----------------------------------------------

            for position, chunk in enumerate(chunks):

                connection.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id,
                        text,
                        page_number,
                        position,
                        embedding,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    (
                        document_id,
                        chunk,
                        page_number + 1,
                        position,
                        None
                    )
                )

                chunks_created += 1

        # ----------------------------------------------------
        # No extractable text
        # ----------------------------------------------------

        if chunks_created == 0:

            message = (
                "No extractable text found in this PDF. "
                "The document may be scanned/image-only. "
                "OCR is required for text extraction."
            )

            connection.execute(
                """
                UPDATE documents
                SET
                    processing_status = ?,
                    page_count = ?,
                    error_message = ?,
                    processed_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    "failed",
                    total_pages,
                    message,
                    document_id
                )
            )

            connection.commit()

            if pdf:
                pdf.close()

            return {
                "status": "failed",
                "document_id": document_id,
                "total_pages": total_pages,
                "text_pages": text_pages,
                "scanned_pages": scanned_pages,
                "empty_pages": empty_pages,
                "chunks_created": 0,
                "message": message
            }

        # ----------------------------------------------------
        # Processing message
        # ----------------------------------------------------

        if scanned_pages > 0:

            processing_message = (
                f"Processed successfully. "
                f"{scanned_pages} scanned/image-only page(s) "
                f"detected; OCR may be required for text "
                f"extraction from those pages."
            )

        elif empty_pages > 0:

            processing_message = (
                f"Processed successfully. "
                f"{empty_pages} empty page(s) detected."
            )

        else:

            processing_message = (
                "Processed successfully."
            )

        # ----------------------------------------------------
        # Mark document as processed
        # ----------------------------------------------------

        connection.execute(
            """
            UPDATE documents
            SET
                processing_status = ?,
                page_count = ?,
                error_message = ?,
                processed_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                "processed",
                total_pages,
                processing_message,
                document_id
            )
        )

        connection.commit()

        # ----------------------------------------------------
        # Close PDF BEFORE rebuilding FAISS
        # ----------------------------------------------------

        if pdf:

            pdf.close()
            pdf = None

        # ----------------------------------------------------
        # Close database connection
        # ----------------------------------------------------

        connection.close()
        connection = None

        # ====================================================
        # UPDATE FAISS VECTOR INDEX
        # ====================================================

        print()
        print("Updating FAISS vector index...")
        print()

        vector_result = rebuild_index()

        print()
        print("FAISS update completed.")
        print()

        # ----------------------------------------------------
        # Final result
        # ----------------------------------------------------

        return {
            "status": "success",
            "document_id": document_id,
            "total_pages": total_pages,
            "text_pages": text_pages,
            "scanned_pages": scanned_pages,
            "empty_pages": empty_pages,
            "chunks_created": chunks_created,
            "message": processing_message,
            "vector_index": vector_result
        }

    except Exception as error:

        print()
        print("PDF PROCESSING ERROR")
        print(error)
        print()

        # ----------------------------------------------------
        # Close PDF
        # ----------------------------------------------------

        try:

            if pdf:
                pdf.close()

        except Exception:
            pass

        # ----------------------------------------------------
        # Update failed status
        # ----------------------------------------------------

        try:

            if connection:

                connection.execute(
                    """
                    UPDATE documents
                    SET
                        processing_status = ?,
                        error_message = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (
                        "failed",
                        str(error),
                        document_id
                    )
                )

                connection.commit()

        except Exception as database_error:

            print(
                "Could not update failed status:"
            )

            print(database_error)

        finally:

            try:

                if connection:
                    connection.close()

            except Exception:
                pass

        return {
            "status": "error",
            "document_id": document_id,
            "message": str(error)
        }


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("DOCURAG PDF PROCESSOR TEST")
    print("=" * 60)

    # Change this ID when testing another document
    test_document_id = 1

    print()
    print(
        f"Processing document ID: {test_document_id}"
    )

    result = process_pdf(
        test_document_id
    )

    print()
    print("Processing Result:")
    print(
        f"Status: {result.get('status')}"
    )
    print(
        f"Document ID: {result.get('document_id')}"
    )

    if "total_pages" in result:
        print(
            f"Total pages: {result.get('total_pages')}"
        )

    if "text_pages" in result:
        print(
            f"Text pages: {result.get('text_pages')}"
        )

    if "scanned_pages" in result:
        print(
            f"Scanned pages: {result.get('scanned_pages')}"
        )

    if "empty_pages" in result:
        print(
            f"Empty pages: {result.get('empty_pages')}"
        )

    if "chunks_created" in result:
        print(
            f"Chunks created: {result.get('chunks_created')}"
        )

    if "message" in result:
        print(
            f"Message: {result.get('message')}"
        )

    if "vector_index" in result:
        print(
            f"Vector index: {result.get('vector_index')}"
        )

    print()