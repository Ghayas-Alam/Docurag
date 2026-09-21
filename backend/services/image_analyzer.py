

import os
import sys
import json
import base64
import mimetypes

from google import genai


# ==========================================
# PROJECT PATHS
# ==========================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

BACKEND_ROOT = os.path.join(
    PROJECT_ROOT,
    "backend"
)

sys.path.append(PROJECT_ROOT)
sys.path.append(BACKEND_ROOT)


from database.database import get_db_connection


# ==========================================
# GEMINI CLIENT
# ==========================================

client = genai.Client()


# ==========================================
# IMAGE ANALYSIS
# ==========================================

def analyze_image(image_path):

    if not os.path.exists(image_path):

        raise Exception(
            "Image file not found"
        )

    mime_type, _ = mimetypes.guess_type(
        image_path
    )

    if not mime_type:

        mime_type = "image/png"

    with open(
        image_path,
        "rb"
    ) as image_file:

        image_bytes = image_file.read()

    image_base64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    prompt = """
Analyze this document image carefully.

Return ONLY valid JSON using exactly this structure:

{
    "description": "A clear description of the image",
    "objects": ["object1", "object2"],
    "extracted_text": "Any readable text in the image",
    "orientation": "portrait or landscape or unknown",
    "colors": ["color1", "color2"],
    "anomalies": "Any unusual or potentially corrupted visual content",
    "confidence": 0.0
}

Rules:

1. Describe what is actually visible.
2. Extract readable text if present.
3. Do not invent information.
4. If no objects are detected, return an empty list.
5. If no readable text exists, return an empty string.
6. If colors cannot be determined, return an empty list.
7. Confidence must be a number between 0 and 1.
8. Return ONLY JSON.
"""

    try:

        interaction = client.interactions.create(
            model="gemini-3.1-flash-lite",
            input=[
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image",
                    "data": image_base64,
                    "mime_type": mime_type
                }
            ]
        )

        response_text = (
            interaction.output_text.strip()
        )

        # ----------------------------------
        # Remove markdown JSON fences
        # ----------------------------------

        if response_text.startswith(
            "```"
        ):

            response_text = (
                response_text
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        analysis = json.loads(
            response_text
        )

        return analysis

    except json.JSONDecodeError:

        return {
            "description":
                response_text,

            "objects": [],

            "extracted_text":
                "",

            "orientation":
                "unknown",

            "colors": [],

            "anomalies":
                "",

            "confidence":
                0.0,

            "raw_response":
                response_text
        }

    except Exception as error:

        raise Exception(
            f"Gemini image analysis failed: "
            f"{str(error)}"
        )


# ==========================================
# SAVE ANALYSIS TO DATABASE
# ==========================================

def analyze_document_images(
    document_id
):

    connection = get_db_connection()

    try:

        images = connection.execute(
            """
            SELECT
                id,
                page_number,
                image_index,
                image_path,
                image_type
            FROM image_analysis
            WHERE document_id = ?
            ORDER BY
                page_number,
                image_index
            """,
            (document_id,)
        ).fetchall()

        if not images:

            return {
                "document_id":
                    document_id,

                "images_found":
                    0,

                "images_analyzed":
                    0,

                "status":
                    "no_images"
            }

        analyzed_count = 0

        for image in images:

            print(
                f"\nAnalyzing image "
                f"{image['image_index']} "
                f"on page "
                f"{image['page_number']}..."
            )

            try:

                analysis = analyze_image(
                    image["image_path"]
                )

                objects = analysis.get(
                    "objects",
                    []
                )

                colors = analysis.get(
                    "colors",
                    []
                )

                connection.execute(
                    """
                    UPDATE image_analysis

                    SET
                        objects = ?,
                        extracted_text = ?,
                        orientation = ?,
                        colors = ?,
                        anomalies = ?,
                        description = ?,
                        raw_analysis = ?

                    WHERE id = ?
                    """,
                    (
                        json.dumps(
                            objects
                        ),

                        analysis.get(
                            "extracted_text",
                            ""
                        ),

                        analysis.get(
                            "orientation",
                            "unknown"
                        ),

                        json.dumps(
                            colors
                        ),

                        analysis.get(
                            "anomalies",
                            ""
                        ),

                        analysis.get(
                            "description",
                            ""
                        ),

                        json.dumps(
                            analysis
                        ),

                        image["id"]
                    )
                )

                connection.commit()

                analyzed_count += 1

                print(
                    "Analysis saved successfully."
                )

            except Exception as error:

                print(
                    f"Failed: {str(error)}"
                )

        return {

            "document_id":
                document_id,

            "images_found":
                len(images),

            "images_analyzed":
                analyzed_count,

            "status":
                "completed"

        }

    finally:

        connection.close()


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print(
        "\n================================"
    )

    print(
        "DOCURAG GEMINI IMAGE ANALYSIS"
    )

    print(
        "================================"
    )

    document_id = 1

    print(
        f"\nDocument ID: {document_id}"
    )

    try:

        result = analyze_document_images(
            document_id
        )

        print(
            "\n================================"
        )

        print(
            "ANALYSIS COMPLETED"
        )

        print(
            "================================"
        )

        print(
            f"Images found: "
            f"{result['images_found']}"
        )

        print(
            f"Images analyzed: "
            f"{result['images_analyzed']}"
        )

        print(
            f"Status: "
            f"{result['status']}"
        )

    except Exception as error:

        print(
            "\nAnalysis failed:"
        )

        print(
            str(error)
        )