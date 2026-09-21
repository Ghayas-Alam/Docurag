import os
import sys
import json

from google import genai
from google.genai import types

# ============================================================
# PATH SETUP
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_ROOT)

sys.path.insert(0, BACKEND_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from database.database import get_db_connection


# ============================================================
# GEMINI
# ============================================================
MODEL_NAME = "gemini-3.1-flash-lite"

client = genai.Client()


# ============================================================
# SUPPORTED IMAGE TYPES
# ============================================================
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


# ============================================================
# ANALYZE IMAGE
# ============================================================
def analyze_uploaded_image(
    image_path,
    document_id,
    page_number=1,
    image_index=0
):
    """
    Analyze image using Gemini Vision.

    Stores:
    1. Image analysis in image_analysis table
    2. Searchable content in document_chunks table

    The document_chunks entry is required because the
    FAISS vector store searches document_chunks.
    """

    # ========================================================
    # VALIDATE FILE
    # ========================================================
    if not image_path:
        raise ValueError("Image path is required.")

    if not os.path.exists(image_path):
        raise FileNotFoundError(
            f"Image file not found: {image_path}"
        )

    if os.path.getsize(image_path) == 0:
        raise ValueError("Image file is empty.")

    extension = os.path.splitext(image_path)[1].lower()

    mime_type = MIME_TYPES.get(extension)

    if not mime_type:
        raise ValueError(
            f"Unsupported image format: {extension}"
        )

    # ========================================================
    # READ IMAGE
    # ========================================================
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()

    if not image_bytes:
        raise ValueError("Could not read image data.")

    # ========================================================
    # GEMINI PROMPT
    # ========================================================
    prompt = """
Analyze this image for a document and image search system.

Return ONLY valid JSON.

Use exactly these fields:

{
  "description": "Detailed but concise description of the image",
  "objects": "Important objects visible in the image",
  "extracted_text": "All clearly readable text visible in the image",
  "orientation": "portrait, landscape, square, or unknown",
  "colors": "Important dominant colors",
  "anomalies": "Important unusual elements, or none",
  "confidence": 0.0
}

Rules:

1. Read all clearly visible text accurately.
2. Preserve wording, numbers, dates, headings and symbols.
3. Do not invent text that is not visible.
4. If no readable text exists, use an empty string.
5. Describe the actual visible contents of the image.
6. Mention important objects, people, diagrams, charts,
   documents, logos or other visible elements.
7. Confidence must be a number between 0 and 1.
8. Return ONLY the JSON object.
9. Do not use Markdown code fences.
"""

    # ========================================================
    # GEMINI IMAGE PROCESSING
    # ========================================================
    try:

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type
                )
            ]
        )

    except Exception as e:

        raise RuntimeError(
            f"Gemini image processing failed: {str(e)}"
        ) from e

    # ========================================================
    # GET RESPONSE
    # ========================================================
    raw_response = ""

    if response is not None:
        raw_response = (
            response.text or ""
        ).strip()

    if not raw_response:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    # ========================================================
    # CLEAN JSON
    # ========================================================
    if raw_response.startswith("```json"):
        raw_response = raw_response[7:]

    elif raw_response.startswith("```"):
        raw_response = raw_response[3:]

    if raw_response.endswith("```"):
        raw_response = raw_response[:-3]

    raw_response = raw_response.strip()

    # ========================================================
    # PARSE JSON
    # ========================================================
    try:

        analysis = json.loads(
            raw_response
        )

    except json.JSONDecodeError:

        start_index = raw_response.find("{")
        end_index = raw_response.rfind("}")

        if (
            start_index != -1
            and end_index != -1
            and end_index > start_index
        ):

            json_text = raw_response[
                start_index:end_index + 1
            ]

            try:

                analysis = json.loads(
                    json_text
                )

            except json.JSONDecodeError:

                analysis = {
                    "description": raw_response,
                    "objects": "",
                    "extracted_text": "",
                    "orientation": "unknown",
                    "colors": "",
                    "anomalies": "none",
                    "confidence": 0.0
                }

        else:

            analysis = {
                "description": raw_response,
                "objects": "",
                "extracted_text": "",
                "orientation": "unknown",
                "colors": "",
                "anomalies": "none",
                "confidence": 0.0
            }

    # ========================================================
    # NORMALIZE FIELDS
    # ========================================================
    description = str(
        analysis.get("description", "")
    ).strip()

    objects = str(
        analysis.get("objects", "")
    ).strip()

    extracted_text = str(
        analysis.get("extracted_text", "")
    ).strip()

    orientation = str(
        analysis.get("orientation", "unknown")
    ).strip()

    colors = str(
        analysis.get("colors", "")
    ).strip()

    anomalies = str(
        analysis.get("anomalies", "none")
    ).strip()

    try:

        confidence = float(
            analysis.get(
                "confidence",
                0.0
            )
        )

    except (TypeError, ValueError):

        confidence = 0.0

    confidence = max(
        0.0,
        min(1.0, confidence)
    )

    # ========================================================
    # CREATE SEARCHABLE TEXT
    # ========================================================
    searchable_parts = []

    if extracted_text:
        searchable_parts.append(
            "Extracted text:\n"
            + extracted_text
        )

    if description:
        searchable_parts.append(
            "Image description:\n"
            + description
        )

    if objects:
        searchable_parts.append(
            "Objects and visible elements:\n"
            + objects
        )

    if orientation:
        searchable_parts.append(
            "Orientation:\n"
            + orientation
        )

    if colors:
        searchable_parts.append(
            "Colors:\n"
            + colors
        )

    if anomalies:
        searchable_parts.append(
            "Anomalies:\n"
            + anomalies
        )

    searchable_text = "\n\n".join(
        searchable_parts
    ).strip()

    if not searchable_text:
        raise RuntimeError(
            "Gemini did not return any searchable "
            "information for this image."
        )

    # ========================================================
    # DATABASE
    # ========================================================
    connection = get_db_connection()

    try:

        # ====================================================
        # 1. SAVE IMAGE ANALYSIS
        # ====================================================
        cursor = connection.execute(
            """
            INSERT INTO image_analysis (
                document_id,
                page_number,
                image_index,
                image_path,
                image_type,
                objects,
                extracted_text,
                orientation,
                colors,
                anomalies,
                description,
                raw_analysis
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                page_number,
                image_index,
                image_path,
                mime_type,
                objects,
                extracted_text,
                orientation,
                colors,
                anomalies,
                description,
                raw_response
            )
        )

        image_id = cursor.lastrowid

        # ====================================================
        # 2. SAVE IMAGE CONTENT AS RAG CHUNK
        # ====================================================
        #
        # IMPORTANT:
        # vector_store.py searches document_chunks.
        # Therefore image content MUST be inserted here.
        #
        cursor = connection.execute(
            """
            INSERT INTO document_chunks (
                document_id,
                text,
                page_number,
                position
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                document_id,
                searchable_text,
                page_number,
                image_index
            )
        )

        chunk_id = cursor.lastrowid

        # ====================================================
        # COMMIT EVERYTHING
        # ====================================================
        connection.commit()

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()

    # ========================================================
    # RETURN RESULT
    # ========================================================
    return {
        "status": "success",
        "image_id": image_id,
        "chunk_id": chunk_id,
        "document_id": document_id,
        "page_number": page_number,
        "image_index": image_index,
        "image_path": image_path,
        "image_type": mime_type,
        "description": description,
        "objects": objects,
        "extracted_text": extracted_text,
        "orientation": orientation,
        "colors": colors,
        "anomalies": anomalies,
        "confidence": confidence,
        "searchable_text": searchable_text
    }


# ============================================================
# DIRECT TEST
# ============================================================
if __name__ == "__main__":

    print("=" * 60)
    print("DOCURAG IMAGE PROCESSOR / GEMINI OCR")
    print("=" * 60)

    print(
        f"Gemini model : {MODEL_NAME}"
    )

    print(
        "Supported   : PNG, JPG, JPEG"
    )

    print(
        "RAG chunks  : ENABLED"
    )

    print(
        "Image processor loaded successfully."
    )

    print("=" * 60)