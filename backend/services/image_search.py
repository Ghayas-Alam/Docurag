import os
import sys
import json
import re
import sqlite3

from sentence_transformers import SentenceTransformer


# =========================================================
# PATH SETUP
# =========================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from database.database import get_db_connection


# =========================================================
# MODEL
# =========================================================

MODEL_NAME = "all-MiniLM-L6-v2"

print("Loading image search embedding model...")
model = SentenceTransformer(MODEL_NAME)
print("Image search embedding model loaded.")


# =========================================================
# STOP WORDS
# =========================================================

STOP_WORDS = {
    "what", "is", "are", "the", "a", "an",
    "in", "on", "of", "to", "does", "do",
    "image", "picture", "photo", "shown",
    "show", "present", "there", "this", "that",
    "tell", "me", "about", "can", "you",
    "please", "describe", "give", "all",
    "its", "their", "it"
}


# =========================================================
# TOKENIZE
# =========================================================

def tokenize(text):

    if not text:
        return set()

    words = re.findall(r"[a-zA-Z0-9]+", text.lower())

    return {
        word
        for word in words
        if word not in STOP_WORDS and len(word) > 1
    }


# =========================================================
# DETECT INTENT
# =========================================================

def detect_intent(question):

    q = question.lower().strip()

    # ---------------- TEXT ----------------

    text_phrases = [
        "what does the image say",
        "what does image say",
        "what is written",
        "what is written in",
        "what is written on",
        "what text",
        "read the text",
        "text in the image",
        "text on the image",
        "written on the image",
        "written in the image",
        "words in the image",
        "ocr"
    ]

    if any(p in q for p in text_phrases):
        return "text"

    # ---------------- OBJECTS ----------------

    object_phrases = [
        "what objects",
        "objects in the image",
        "objects are present",
        "what is present",
        "things in the image",
        "items in the image",
        "what can you see",
        "what do you see"
    ]

    if any(p in q for p in object_phrases):
        return "objects"

    # ---------------- COLORS ----------------

    color_phrases = [
        "what colors",
        "what colour",
        "what colours",
        "what color",
        "colors in the image",
        "colours in the image",
        "color of the image",
        "colour of the image"
    ]

    if any(p in q for p in color_phrases):
        return "colors"

    # ---------------- ORIENTATION ----------------

    orientation_phrases = [
        "orientation",
        "portrait or landscape",
        "image orientation"
    ]

    if any(p in q for p in orientation_phrases):
        return "orientation"

    # ---------------- DESCRIPTION ----------------

    description_phrases = [
        "describe the image",
        "describe image",
        "describe this image",
        "describe the picture",
        "give a description",
        "description of the image"
    ]

    if any(p in q for p in description_phrases):
        return "description"

    return "general"


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_value(value):

    if value is None:
        return ""

    return str(value).strip()


def meaningful_text(text):

    if not text:
        return False

    text = text.strip()

    # Ignore meaningless OCR
    meaningless = {
        "</>",
        "<>",
        "/>",
        "—",
        "-",
        "_",
        ".",
        "..",
        "...",
    }

    if text.lower() in meaningless:
        return False

    # Need at least some alphanumeric content
    if len(re.findall(r"[a-zA-Z0-9]", text)) < 3:
        return False

    return True


# =========================================================
# KEYWORD SCORE
# =========================================================

def keyword_score(question, text):

    q_tokens = tokenize(question)
    t_tokens = tokenize(text)

    if not q_tokens or not t_tokens:
        return 0.0

    matched = q_tokens.intersection(t_tokens)

    return len(matched) / len(q_tokens)


# =========================================================
# SEMANTIC SCORE
# =========================================================

def semantic_similarity(question, text):

    if not text:
        return 0.0

    try:

        q_embedding = model.encode(
            [question],
            normalize_embeddings=True
        )[0]

        t_embedding = model.encode(
            [text],
            normalize_embeddings=True
        )[0]

        score = float(q_embedding @ t_embedding)

        return max(0.0, min(1.0, score))

    except Exception:

        return 0.0


# =========================================================
# IMAGE SEARCH
# =========================================================

def search_image_analysis(question, top_k=5):

    connection = get_db_connection()
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            ia.id AS image_id,
            ia.document_id,
            d.original_filename AS document_name,
            d.file_type AS document_file_type,
            ia.page_number,
            ia.image_index,
            ia.image_path,
            ia.image_type,
            ia.description,
            ia.extracted_text,
            ia.objects,
            ia.orientation,
            ia.colors,
            ia.anomalies
        FROM image_analysis ia
        JOIN documents d
            ON ia.document_id = d.id
        WHERE d.processing_status = 'processed'
        ORDER BY ia.id
    """)

    rows = cursor.fetchall()

    connection.close()

    if not rows:
        return []

    intent = detect_intent(question)

    results = []

    # Encode question only once
    question_embedding = model.encode(
        [question],
        normalize_embeddings=True
    )[0]

    for row in rows:

        description = clean_value(row["description"])
        extracted_text = clean_value(row["extracted_text"])
        objects = clean_value(row["objects"])
        orientation = clean_value(row["orientation"])
        colors = clean_value(row["colors"])
        anomalies = clean_value(row["anomalies"])

        has_meaningful_text = meaningful_text(extracted_text)

        # -------------------------------------------------
        # GENERAL CONTENT
        # -------------------------------------------------

        general_text = " ".join(
            value for value in [
                description,
                extracted_text if has_meaningful_text else "",
                objects,
                orientation,
                colors,
                anomalies
            ]
            if value
        )

        # -------------------------------------------------
        # TARGET FIELD
        # -------------------------------------------------

        if intent == "text":
            target_text = extracted_text if has_meaningful_text else ""

        elif intent == "objects":
            target_text = objects

        elif intent == "colors":
            target_text = colors

        elif intent == "orientation":
            target_text = orientation

        elif intent == "description":
            target_text = description

        else:
            target_text = general_text

        # -------------------------------------------------
        # EMBEDDING
        # -------------------------------------------------

        semantic = 0.0

        if target_text:

            try:

                target_embedding = model.encode(
                    [target_text],
                    normalize_embeddings=True
                )[0]

                semantic = float(
                    question_embedding @ target_embedding
                )

                semantic = max(
                    0.0,
                    min(1.0, semantic)
                )

            except Exception:

                semantic = 0.0

        # -------------------------------------------------
        # KEYWORD
        # -------------------------------------------------

        keyword = keyword_score(
            question,
            target_text
        )

        # =================================================
        # TEXT INTENT
        # =================================================

        if intent == "text":

            if not has_meaningful_text:

                score = 0.0

            else:

                # Text presence is the most important thing.
                #
                # Generic query like:
                # "What does the image say?"
                # should not prefer decorative images
                # whose OCR is only "</>".

                text_presence_bonus = 0.55

                # More useful OCR gets a small bonus,
                # but cap it so huge text does not dominate.
                text_length_bonus = min(
                    len(extracted_text) / 100.0,
                    0.20
                )

                score = (
                    text_presence_bonus
                    + text_length_bonus
                    + (0.15 * semantic)
                    + (0.10 * keyword)
                )

        # =================================================
        # OBJECT INTENT
        # =================================================

        elif intent == "objects":

            if not objects:

                score = 0.0

            else:

                score = (
                    0.55 * semantic
                    + 0.45 * keyword
                )

        # =================================================
        # COLOR INTENT
        # =================================================

        elif intent == "colors":

            if not colors:

                score = 0.0

            else:

                score = (
                    0.60 * semantic
                    + 0.40 * keyword
                )

        # =================================================
        # ORIENTATION INTENT
        # =================================================

        elif intent == "orientation":

            if not orientation:

                score = 0.0

            else:

                score = (
                    0.60 * semantic
                    + 0.40 * keyword
                )

        # =================================================
        # DESCRIPTION INTENT
        # =================================================

        elif intent == "description":

            if not description:

                score = 0.0

            else:

                score = (
                    0.70 * semantic
                    + 0.30 * keyword
                )

        # =================================================
        # GENERAL INTENT
        # =================================================

        else:

            score = (
                0.70 * semantic
                + 0.30 * keyword
            )

        # -------------------------------------------------
        # STANDALONE IMAGE BONUS
        # -------------------------------------------------

        # If the user uploaded an actual image rather than
        # an image extracted from a PDF, give it a small
        # relevance boost for generic image searches.

        file_type = clean_value(
            row["document_file_type"]
        ).lower()

        standalone_image = (
            file_type.startswith("image/")
            or clean_value(row["image_type"]).lower()
            in {"image/png", "image/jpeg", "image/jpg"}
        )

        if standalone_image and score > 0:

            score += 0.15

        # -------------------------------------------------
        # RESULT
        # -------------------------------------------------

        results.append({
            "image_id": row["image_id"],
            "document_id": row["document_id"],
            "document_name": row["document_name"],
            "page_number": row["page_number"],
            "image_index": row["image_index"],
            "image_path": row["image_path"],
            "image_type": row["image_type"],
            "description": description,
            "extracted_text": extracted_text,
            "objects": objects,
            "orientation": orientation,
            "colors": colors,
            "anomalies": anomalies,
            "semantic_score": round(semantic, 4),
            "keyword_score": round(keyword, 4),
            "score": round(score, 4),
            "intent": intent
        })

    # ---------------------------------------------------------
    # SORT
    # ---------------------------------------------------------

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    # ---------------------------------------------------------
    # REMOVE ZERO RESULTS
    # ---------------------------------------------------------

    meaningful_results = [
        result
        for result in results
        if result["score"] > 0
    ]

    if not meaningful_results:
        return []

    return meaningful_results[:top_k]


# =========================================================
# PUBLIC FUNCTION
# =========================================================

def image_search(question, top_k=5):

    return search_image_analysis(
        question,
        top_k
    )


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    print("\n" + "=" * 60)
    print("DOCURAG IMAGE SEARCH TEST")
    print("=" * 60)

    questions = [
        "What does the image say?",
        "What objects are present in the image?",
        "What is shown in the image?",
        "Describe the image",
        "What are the colors in the image?",
        "table tennis paddles"
    ]

    for question in questions:

        print("\n" + "-" * 60)
        print("QUESTION:", question)
        print("-" * 60)

        results = image_search(question)

        print(
            json.dumps(
                results,
                indent=2,
                ensure_ascii=False
            )
        )