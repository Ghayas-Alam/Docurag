import os
import sys
import json
import base64

from google import genai

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
# ANALYZE IMAGE / OCR
# ============================================================
def analyze_uploaded_image(
    image_path,
    document_id,
    page_number=1,
    image_index=0
):
    """Analyze an image with Gemini and extract visible text."""

    if not os.path.exists(image_path):
        raise FileNotFoundError("Image file not found.")

    if os.path.getsize(image_path) == 0:
        raise ValueError("Image file is empty.")

    extension = os.path.splitext(image_path)[1].lower()
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg"
    }
    mime_type = mime_types.get(extension)

    if not mime_type:
        raise ValueError("Unsupported image format.")

    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()

    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

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
1. Read all clearly visible text as accurately as possible.
2. Preserve wording, numbers, dates, headings and symbols when readable.
3. Do not invent text that is not visible.
4. If no readable text exists, use an empty string.
5. Keep the description factual.
6. Confidence must be a number between 0 and 1.
"""

    interaction = client.interactions.create(
        model=MODEL_NAME,
        input=[
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "data": encoded_image,
                "mime_type": mime_type
            }
        ]
    )

    raw_response = (interaction.output_text or "").strip()

    if raw_response.startswith("```json"):
        raw_response = raw_response[7:]
    if raw_response.endswith("```"):
        raw_response = raw_response[:-3]
    raw_response = raw_response.strip()

    try:
        analysis = json.loads(raw_response)
    except json.JSONDecodeError:
        analysis = {
            "description": raw_response,
            "objects": "",
            "extracted_text": "",
            "orientation": "unknown",
            "colors": "",
            "anomalies": "",
            "confidence": 0.0
        }

    description = str(analysis.get("description", ""))
    objects = str(analysis.get("objects", ""))
    extracted_text = str(analysis.get("extracted_text", "")).strip()
    orientation = str(analysis.get("orientation", "unknown"))
    colors = str(analysis.get("colors", ""))
    anomalies = str(analysis.get("anomalies", ""))

    try:
        confidence = float(analysis.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    connection = get_db_connection()
    try:
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
        connection.commit()
        image_id = cursor.lastrowid
    finally:
        connection.close()

    return {
        "status": "success",
        "image_id": image_id,
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
        "confidence": confidence
    }


if __name__ == "__main__":
    print("DOCURAG IMAGE PROCESSOR / GEMINI OCR")
    print("Image processor loaded successfully.")
