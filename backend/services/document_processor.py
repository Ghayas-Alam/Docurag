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
from services.image_file_processor import analyze_uploaded_image

# ============================================================
# CONFIGURATION
# ============================================================
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 1000
OCR_SCALE = 2.0

EXTRACTED_IMAGES_FOLDER = os.path.join(
    PROJECT_ROOT,
    "extracted_images"
)
os.makedirs(EXTRACTED_IMAGES_FOLDER, exist_ok=True)


# ============================================================
# CREATE TEXT CHUNKS
# ============================================================
def create_chunks(
    text,
    chunk_size=CHUNK_SIZE,
    overlap=CHUNK_OVERLAP
):
    if not text:
        return []

    step = chunk_size - overlap
    if step <= 0:
        raise ValueError(
            "Chunk overlap must be smaller than chunk size."
        )

    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + chunk_size]
        if not chunk:
            break
        if chunk.strip():
            chunks.append(chunk)

    return chunks


# ============================================================
# STORE CHUNKS
# ============================================================
def insert_text_chunks(
    connection,
    document_id,
    page_number,
    text
):
    chunks = create_chunks(text)
    created = 0

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
                page_number,
                position,
                None
            )
        )
        created += 1

    return created


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
            SELECT id, original_filename, file_path, file_type
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
        file_type = (document["file_type"] or "").lower()

        # ----------------------------------------------------
        # Validate
        # ----------------------------------------------------
        if file_type != "pdf":
            message = "Only PDF processing is currently supported."
            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?, error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                ("failed", message, document_id)
            )
            connection.commit()
            return {
                "status": "error",
                "document_id": document_id,
                "message": message
            }

        if not file_path:
            message = "Document file path is missing."
            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?, error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                ("failed", message, document_id)
            )
            connection.commit()
            return {
                "status": "error",
                "document_id": document_id,
                "message": message
            }

        if not os.path.exists(file_path):
            message = "Document file was not found on disk."
            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?, error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                ("failed", message, document_id)
            )
            connection.commit()
            return {
                "status": "error",
                "document_id": document_id,
                "message": message
            }

        if os.path.getsize(file_path) == 0:
            message = "Document file is empty."
            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?, error_message = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                ("failed", message, document_id)
            )
            connection.commit()
            return {
                "status": "error",
                "document_id": document_id,
                "message": message
            }

        # ----------------------------------------------------
        # Mark processing
        # ----------------------------------------------------
        connection.execute(
            """
            UPDATE documents
            SET processing_status = ?, error_message = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            ("processing", document_id)
        )
        connection.commit()

        # ----------------------------------------------------
        # Open PDF
        # ----------------------------------------------------
        print("Opening PDF...")
        pdf = pymupdf.open(file_path)

        total_pages = len(pdf)
        text_pages = 0
        scanned_pages = 0
        ocr_pages = 0
        ocr_failed_pages = 0
        empty_pages = 0
        chunks_created = 0

        print(f"Total pages: {total_pages}")

        # ----------------------------------------------------
        # Clear previous processing results so re-processing
        # does not duplicate chunks/OCR records.
        # ----------------------------------------------------
        connection.execute(
            "DELETE FROM document_chunks WHERE document_id = ?",
            (document_id,)
        )
        connection.execute(
            "DELETE FROM image_analysis WHERE document_id = ?",
            (document_id,)
        )
        connection.commit()

        # ----------------------------------------------------
        # Folder for rendered scanned pages
        # ----------------------------------------------------
        document_images_folder = os.path.join(
            EXTRACTED_IMAGES_FOLDER,
            str(document_id)
        )
        os.makedirs(document_images_folder, exist_ok=True)

        # ----------------------------------------------------
        # Process every page
        # ----------------------------------------------------
        for page_index in range(total_pages):
            page = pdf[page_index]
            page_number = page_index + 1

            print(
                f"Processing page {page_number}/{total_pages}..."
            )

            # ------------------------------------------------
            # First try native PDF text extraction.
            # ------------------------------------------------
            text = page.get_text("text")
            text = text.strip() if text else ""

            if text:
                text_pages += 1
                chunks_created += insert_text_chunks(
                    connection,
                    document_id,
                    page_number,
                    text
                )
                connection.commit()
                continue

            # ------------------------------------------------
            # No native text. Check whether the page contains
            # image content and use Gemini Vision as OCR.
            # ------------------------------------------------
            images = page.get_images(full=True)

            if not images:
                empty_pages += 1
                continue

            scanned_pages += 1
            ocr_pages += 1

            image_path = os.path.join(
                document_images_folder,
                f"page_{page_number}.png"
            )

            try:
                print(
                    f"  Rendering page {page_number} for Gemini OCR..."
                )

                matrix = pymupdf.Matrix(
                    OCR_SCALE,
                    OCR_SCALE
                )

                pixmap = page.get_pixmap(
                    matrix=matrix,
                    alpha=False
                )
                pixmap.save(image_path)

                analysis_result = analyze_uploaded_image(
                    image_path,
                    document_id,
                    page_number=page_number,
                    image_index=0
                )

                extracted_text = (
                    analysis_result.get("extracted_text", "")
                    or ""
                ).strip()

                if extracted_text:
                    created = insert_text_chunks(
                        connection,
                        document_id,
                        page_number,
                        extracted_text
                    )
                    chunks_created += created
                    connection.commit()

                    print(
                        f"  Gemini OCR extracted "
                        f"{len(extracted_text)} characters."
                    )
                else:
                    print(
                        "  Gemini OCR returned no readable text."
                    )

            except Exception as ocr_error:
                ocr_failed_pages += 1
                connection.rollback()
                print(
                    f"  OCR failed on page {page_number}: "
                    f"{ocr_error}"
                )

        connection.commit()

        # ----------------------------------------------------
        # Nothing was extracted
        # ----------------------------------------------------
        if chunks_created == 0:
            if ocr_failed_pages:
                message = (
                    "No extractable text was found. "
                    f"Gemini OCR failed on {ocr_failed_pages} page(s)."
                )
            elif ocr_pages:
                message = (
                    "No readable text was found. Gemini OCR was "
                    "attempted on the scanned page(s), but no text "
                    "was extracted."
                )
            else:
                message = (
                    "No extractable text found in this PDF. "
                    "The document may be image-only or empty."
                )

            connection.execute(
                """
                UPDATE documents
                SET processing_status = ?, page_count = ?,
                    error_message = ?, processed_at = datetime('now'),
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

            pdf.close()
            pdf = None
            connection.close()
            connection = None

            return {
                "status": "failed",
                "document_id": document_id,
                "total_pages": total_pages,
                "text_pages": text_pages,
                "scanned_pages": scanned_pages,
                "ocr_pages": ocr_pages,
                "ocr_failed_pages": ocr_failed_pages,
                "empty_pages": empty_pages,
                "chunks_created": 0,
                "message": message
            }

        # ----------------------------------------------------
        # Processing message
        # ----------------------------------------------------
        if ocr_pages and ocr_failed_pages:
            processing_message = (
                "Processed successfully with Gemini OCR. "
                f"{ocr_pages} scanned page(s) were attempted; "
                f"OCR failed on {ocr_failed_pages} page(s)."
            )
        elif ocr_pages:
            processing_message = (
                "Processed successfully. "
                f"{ocr_pages} scanned page(s) were processed "
                "using Gemini OCR."
            )
        elif empty_pages:
            processing_message = (
                "Processed successfully. "
                f"{empty_pages} empty page(s) detected."
            )
        else:
            processing_message = "Processed successfully."

        # ----------------------------------------------------
        # Mark processed
        # ----------------------------------------------------
        connection.execute(
            """
            UPDATE documents
            SET processing_status = ?, page_count = ?,
                error_message = ?, processed_at = datetime('now'),
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
        # Close before FAISS rebuild
        # ----------------------------------------------------
        pdf.close()
        pdf = None
        connection.close()
        connection = None

        print()
        print("Updating FAISS vector index...")
        vector_result = rebuild_index()
        print("FAISS update completed.")

        return {
            "status": "success",
            "document_id": document_id,
            "total_pages": total_pages,
            "text_pages": text_pages,
            "scanned_pages": scanned_pages,
            "ocr_pages": ocr_pages,
            "ocr_failed_pages": ocr_failed_pages,
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

        try:
            if pdf:
                pdf.close()
        except Exception:
            pass

        try:
            if connection:
                connection.execute(
                    """
                    UPDATE documents
                    SET processing_status = ?, error_message = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    ("failed", str(error), document_id)
                )
                connection.commit()
        except Exception as database_error:
            print("Could not update failed status:")
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


if __name__ == "__main__":
    print("DOCURAG PDF PROCESSOR TEST")
    test_document_id = 1
    result = process_pdf(test_document_id)
    print(result)
