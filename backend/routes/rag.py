import os
import sys
import time
import hashlib

from flask import Blueprint, request, jsonify, session

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
from services.cache import (
    create_cache_key,
    get_cache,
    set_cache,
    clear_cache
)
from google import genai

from database.database import get_db_connection

from services.hybrid_search import hybrid_search
from services.image_search import image_search
from services.cache import (
    create_cache_key,
    get_cache,
    set_cache
)


# ============================================================
# BLUEPRINT
# ============================================================

rag_bp = Blueprint(
    "rag",
    __name__
)


# ============================================================
# GEMINI CONFIGURATION
# ============================================================

MODEL_NAME = "gemini-3.1-flash-lite"

client = genai.Client()


# ============================================================
# RAG CONFIGURATION
# ============================================================

# Very weak results should never reach Gemini.
MIN_RELEVANCE_SCORE = 0.20

# Strong result threshold.
STRONG_RELEVANCE_SCORE = 0.35

# Maximum text chunks sent to Gemini.
MAX_TEXT_SOURCES = 5

# Maximum image results.
MAX_IMAGE_SOURCES = 5


# ============================================================
# HELPER: AUTHENTICATION
# ============================================================

def get_current_user_id():

    return session.get(
        "user_id"
    )


# ============================================================
# HELPER: CONVERSATION ID
# ============================================================

def get_conversation_id():

    conversation_id = request.json.get(
        "conversation_id"
    )

    if not conversation_id:

        conversation_id = (
            f"user-{get_current_user_id()}"
        )

    return conversation_id


# ============================================================
# HELPER: CACHE KEY
# ============================================================

def make_cache_key(
    user_id,
    question,
    conversation_id
):

    return create_cache_key(
        user_id,
        question,
        conversation_id
    )


# ============================================================
# HELPER: CLEAN SEARCH RESULTS
# ============================================================

def filter_relevant_results(
    results
):
    """
    Remove very weak search results.

    Also removes low-quality cross-document results when
    stronger relevant results from another document exist.
    """

    if not results:
        return []

    cleaned = []

    # --------------------------------------------------------
    # First remove extremely weak results
    # --------------------------------------------------------

    for result in results:

        score = float(
            result.get(
                "hybrid_score",
                result.get(
                    "similarity",
                    result.get(
                        "semantic_score",
                        0
                    )
                )
            )
        )

        result["final_relevance"] = score

        if score >= MIN_RELEVANCE_SCORE:

            cleaned.append(
                result
            )

    if not cleaned:
        return []

    # --------------------------------------------------------
    # Sort by relevance
    # --------------------------------------------------------

    cleaned.sort(
        key=lambda item: item.get(
            "final_relevance",
            0
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # Find strongest document
    # --------------------------------------------------------

    strongest_document = cleaned[0].get(
        "document_id"
    )

    strongest_document_score = cleaned[0].get(
        "final_relevance",
        0
    )

    # --------------------------------------------------------
    # If there is a clearly strong document match,
    # don't allow weak unrelated documents to pollute
    # the context.
    #
    # Example:
    #
    # JD.pdf = 0.60
    # JD.pdf = 0.30
    # book.pdf = 0.16
    #
    # book.pdf will be removed.
    # --------------------------------------------------------

    if strongest_document_score >= STRONG_RELEVANCE_SCORE:

        focused_results = []

        for result in cleaned:

            document_id = result.get(
                "document_id"
            )

            score = result.get(
                "final_relevance",
                0
            )

            if document_id == strongest_document:

                focused_results.append(
                    result
                )

            elif score >= STRONG_RELEVANCE_SCORE:

                focused_results.append(
                    result
                )

        cleaned = focused_results

    # --------------------------------------------------------
    # Final sorting
    # --------------------------------------------------------

    cleaned.sort(
        key=lambda item: item.get(
            "final_relevance",
            0
        ),
        reverse=True
    )

    return cleaned[
        :MAX_TEXT_SOURCES
    ]


# ============================================================
# HELPER: GET CONVERSATION HISTORY
# ============================================================

def get_conversation_history(
    user_id,
    conversation_id,
    limit=5
):

    connection = get_db_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                question,
                answer,
                created_at
            FROM queries
            WHERE user_id = ?
            AND conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (
                user_id,
                conversation_id,
                limit
            )
        ).fetchall()

        history = []

        for row in reversed(rows):

            history.append(
                {
                    "question": row["question"],
                    "answer": row["answer"]
                }
            )

        return history

    finally:

        connection.close()


# ============================================================
# HELPER: BUILD TEXT CONTEXT
# ============================================================

def build_text_context(
    sources
):

    if not sources:

        return "No relevant text sources were found."

    context_parts = []

    for index, source in enumerate(
        sources,
        start=1
    ):

        document_name = source.get(
            "document_name",
            "Unknown document"
        )

        page_number = source.get(
            "page_number",
            "Unknown"
        )

        text = source.get(
            "text",
            ""
        )

        score = source.get(
            "final_relevance",
            source.get(
                "similarity",
                0
            )
        )

        context_parts.append(
            f"""
SOURCE {index}
Document: {document_name}
Page: {page_number}
Relevance: {float(score):.3f}

Content:
{text}
"""
        )

    return "\n".join(
        context_parts
    )


# ============================================================
# HELPER: BUILD IMAGE CONTEXT
# ============================================================

def is_image_focused_intent(image_sources):
    """
    Return True when the image search identifies the question
    as an image-specific request.

    This prevents unrelated PDF text chunks from being mixed
    into questions such as "What does the image say?".
    """

    if not image_sources:
        return False

    intent = image_sources[0].get("intent")

    return intent in (
        "text",
        "objects",
        "colors",
        "orientation",
        "description"
    )


def build_image_context(
    image_sources
):

    if not image_sources:

        return "No relevant image information was found."

    context_parts = []

    for index, image in enumerate(
        image_sources,
        start=1
    ):

        document_name = image.get(
            "document_name",
            "Unknown document"
        )

        page_number = image.get(
            "page_number",
            "Unknown"
        )

        description = image.get(
            "description",
            ""
        )

        extracted_text = image.get(
            "extracted_text",
            ""
        )

        objects = image.get(
            "objects",
            ""
        )

        colors = image.get(
            "colors",
            ""
        )

        context_parts.append(
            f"""
IMAGE SOURCE {index}
Document: {document_name}
Page: {page_number}

Description:
{description}

Extracted Text:
{extracted_text}

Objects:
{objects}

Colors:
{colors}
"""
        )

    return "\n".join(
        context_parts
    )


# ============================================================
# HELPER: BUILD HISTORY CONTEXT
# ============================================================

def build_history_context(
    history
):

    if not history:

        return "No previous conversation."

    parts = []

    for item in history:

        parts.append(
            f"""
User:
{item["question"]}

Assistant:
{item["answer"]}
"""
        )

    return "\n".join(
        parts
    )


# ============================================================
# HELPER: CONFIDENCE
# ============================================================

def calculate_confidence(
    text_sources,
    image_sources
):

    scores = []

    for source in text_sources:

        score = source.get(
            "final_relevance",
            source.get(
                "similarity",
                0
            )
        )

        scores.append(
            float(score)
        )

    for source in image_sources:

        score = source.get(
            "score",
            0
        )

        scores.append(
            float(score)
        )

    if not scores:

        return 0.0

    # Use strongest few results rather than
    # averaging unrelated weak results.
    scores.sort(
        reverse=True
    )

    top_scores = scores[
        :3
    ]

    confidence = sum(
        top_scores
    ) / len(
        top_scores
    )

    # Keep within 0-1.
    confidence = max(
        0.0,
        min(
            1.0,
            confidence
        )
    )

    return round(
        confidence,
        3
    )


# ============================================================
# ASK QUESTION
# ============================================================

@rag_bp.route(
    "/ask",
    methods=["POST"]
)
def ask_question():

    start_time = time.time()

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    user_id = get_current_user_id()

    if not user_id:

        return jsonify(
            {
                "status": "error",
                "message": "Authentication required"
            }
        ), 401

    # --------------------------------------------------------
    # Validate JSON
    # --------------------------------------------------------

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify(
            {
                "status": "error",
                "message": "JSON request body is required"
            }
        ), 400

    # --------------------------------------------------------
    # Question
    # --------------------------------------------------------

    question = data.get(
        "question",
        ""
    )

    if not isinstance(
        question,
        str
    ):

        return jsonify(
            {
                "status": "error",
                "message": "Question must be text"
            }
        ), 400

    question = question.strip()

    if not question:

        return jsonify(
            {
                "status": "error",
                "message": "Question cannot be empty"
            }
        ), 400

    if len(question) > 2000:

        return jsonify(
            {
                "status": "error",
                "message": "Question is too long"
            }
        ), 400

    # --------------------------------------------------------
    # Conversation
    # --------------------------------------------------------

    conversation_id = get_conversation_id()

    # --------------------------------------------------------
    # CACHE
    # --------------------------------------------------------

    cache_key = make_cache_key(
        user_id,
        question,
        conversation_id
    )

    cached_response = get_cache(
        cache_key
    )

    if cached_response is not None:

        cached_response = dict(
            cached_response
        )

        cached_response["cache_hit"] = True
        cached_response["response_time"] = round(
            time.time() - start_time,
            4
        )

        return jsonify(
            cached_response
        ), 200

    try:

        # ====================================================
        # CONVERSATION HISTORY
        # ====================================================

        history = get_conversation_history(
            user_id,
            conversation_id
        )

        # ====================================================
        # HYBRID TEXT SEARCH
        # ====================================================

        raw_text_results = hybrid_search(
            question,
            top_k=10
        )

        # ====================================================
        # FILTER RELEVANT RESULTS
        # ====================================================

        text_results = filter_relevant_results(
            raw_text_results
        )

        # ====================================================
        # IMAGE SEARCH
        # ====================================================

        try:

            image_results = image_search(
                question,
                top_k=MAX_IMAGE_SOURCES
            )

        except Exception as image_error:

            print(
                "Image search error:"
            )

            print(
                image_error
            )

            image_results = []

        # ====================================================
        # IMAGE RESULT FILTERING
        # ====================================================

        filtered_image_results = []

        for image in image_results:

            score = float(
                image.get(
                    "score",
                    0
                )
            )

            if score > 0:
                filtered_image_results.append(image)

        filtered_image_results.sort(
            key=lambda item: item.get(
                "score",
                0
            ),
            reverse=True
        )

        # ----------------------------------------------------
        # Intent-aware image context selection
        #
        # For image-specific questions such as:
        # "What does the image say?"
        # the image search service marks the result with
        # intent="text". In that case only the strongest
        # image should be sent to Gemini. This prevents
        # unrelated images from other documents polluting
        # the answer.
        #
        # For objects/colors/description/orientation, keep
        # only the strongest 2 matching images.
        # Generic questions can use the normal top-k limit.
        # ----------------------------------------------------

        image_intent = None

        if filtered_image_results:
            image_intent = filtered_image_results[0].get(
                "intent"
            )

        if image_intent in (
            "text",
            "objects",
            "colors",
            "orientation",
            "description"
        ):
            image_results = filtered_image_results[:2]
        else:
            image_results = filtered_image_results[
                :MAX_IMAGE_SOURCES
            ]

        # ----------------------------------------------------
        # If this is a text-reading request, use only the
        # strongest image. The user is asking for the text
        # from the relevant image, not text from every
        # image in the database.
        # ----------------------------------------------------

        if image_intent == "text":
            image_results = filtered_image_results[:1]

        # ====================================================
        # BUILD CONTEXT
        # ====================================================

        # If the question is clearly image-focused, do not mix
        # unrelated document text into the Gemini context.
        # The answer should be grounded in the relevant image.
        if is_image_focused_intent(image_results):
            text_context = "No text sources are used for this image-focused question."
        else:
            text_context = build_text_context(
                text_results
            )

        image_context = build_image_context(
            image_results
        )

        history_context = build_history_context(
            history
        )

        # ====================================================
        # GEMINI PROMPT
        # ====================================================

        prompt = f"""
You are DocuRAG, a document question-answering assistant.

Answer the user's question using ONLY the retrieved document
information provided below.

IMPORTANT RULES:

1. Do not invent information.
2. Do not use outside knowledge when answering the question.
3. If the retrieved information does not contain the answer,
   clearly say that the information was not found in the
   uploaded documents.
4. Prefer the most relevant sources.
5. Do not mention or cite documents that are not relevant
   to the question.
6. Keep the answer clear and useful.
7. If multiple relevant documents contain useful information,
   you may combine them.
8. When information comes from an image, use the image context.
9. Do not treat the relevance score as factual information.
10. Answer the user's exact question.

============================================================
CONVERSATION HISTORY
============================================================

{history_context}

============================================================
RETRIEVED TEXT SOURCES
============================================================

{text_context}

============================================================
RETRIEVED IMAGE INFORMATION
============================================================

{image_context}

============================================================
USER QUESTION
============================================================

{question}

============================================================
FINAL ANSWER
============================================================

Provide a grounded answer based only on the retrieved
information above.
"""

        # ====================================================
        # GEMINI GENERATION
        # ====================================================

        try:

            interaction = client.interactions.create(
                model=MODEL_NAME,
                input=prompt
            )

            answer = interaction.output_text

        except Exception as gemini_error:

            error_text = str(
                gemini_error
            )

            print(
                "Gemini error:"
            )

            print(
                error_text
            )

            # ------------------------------------------------
            # Rate limit
            # ------------------------------------------------

            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
            ):

                return jsonify(
                    {
                        "status": "error",
                        "message": (
                            "AI service rate limit reached. "
                            "Please try again later."
                        )
                    }
                ), 429

            return jsonify(
                {
                    "status": "error",
                    "message": (
                        "Failed to generate AI response"
                    )
                }
            ), 500

        # ====================================================
        # CONFIDENCE
        # ====================================================

        confidence = calculate_confidence(
            text_results,
            image_results
        )

        # ====================================================
        # RESPONSE TIME
        # ====================================================

        response_time = round(
            time.time() - start_time,
            4
        )

        # ====================================================
        # DATABASE
        # ====================================================

        connection = get_db_connection()

        try:

            cursor = connection.execute(
                """
                INSERT INTO queries (
                    user_id,
                    conversation_id,
                    question,
                    answer,
                    confidence,
                    response_time,
                    cache_hit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    conversation_id,
                    question,
                    answer,
                    confidence,
                    response_time,
                    0
                )
            )

            query_id = cursor.lastrowid

            # ------------------------------------------------
            # Save text sources
            # ------------------------------------------------

            sources_to_save = (
                []
                if is_image_focused_intent(image_results)
                else text_results
            )

            for rank, source in enumerate(
                sources_to_save,
                start=1
            ):

                similarity = source.get(
                    "final_relevance",
                    source.get(
                        "similarity",
                        source.get(
                            "semantic_score",
                            0
                        )
                    )
                )

                connection.execute(
                    """
                    INSERT INTO query_sources (
                        query_id,
                        document_id,
                        chunk_id,
                        similarity,
                        source_page,
                        retrieved_text,
                        image_context,
                        rank
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        query_id,
                        source.get(
                            "document_id"
                        ),
                        source.get(
                            "chunk_id"
                        ),
                        float(
                            similarity
                        ),
                        source.get(
                            "page_number"
                        ),
                        source.get(
                            "text",
                            ""
                        ),
                        None,
                        rank
                    )
                )

            # ------------------------------------------------
            # Commit
            # ------------------------------------------------

            connection.commit()

        finally:

            connection.close()

        # ====================================================
        # RESPONSE
        # ====================================================

        response = {
            "status": "success",
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "conversation_id": conversation_id,
            "cache_hit": False,
            "response_time": response_time,
            "sources": text_results,
            "image_sources": image_results
        }

        # ====================================================
        # CACHE RESPONSE
        # ====================================================

        set_cache(
            cache_key,
            response
        )

        return jsonify(
            response
        ), 200

    except Exception as error:

        print()
        print("RAG ERROR:")
        print(error)
        print()

        return jsonify(
            {
                "status": "error",
                "message": "Failed to process question",
                "error": str(error)
            }
        ), 500


# ============================================================
# NEW CHAT
# ============================================================

@rag_bp.route(
    "/new_chat",
    methods=["POST"]
)
def new_chat():

    user_id = get_current_user_id()

    if not user_id:

        return jsonify(
            {
                "status": "error",
                "message": "Authentication required"
            }
        ), 401

    conversation_id = (
        f"user-{user_id}-{int(time.time() * 1000)}"
    )

    return jsonify(
        {
            "status": "success",
            "message": "New conversation created",
            "conversation_id": conversation_id
        }
    ), 200


# ============================================================
# CHAT HISTORY
# ============================================================

@rag_bp.route(
    "/history",
    methods=["GET"]
)
def get_history():

    user_id = get_current_user_id()

    if not user_id:

        return jsonify(
            {
                "status": "error",
                "message": "Authentication required"
            }
        ), 401

    conversation_id = request.args.get(
        "conversation_id"
    )

    connection = get_db_connection()

    try:

        if conversation_id:

            rows = connection.execute(
                """
                SELECT
                    id,
                    conversation_id,
                    question,
                    answer,
                    confidence,
                    response_time,
                    cache_hit,
                    created_at
                FROM queries
                WHERE user_id = ?
                AND conversation_id = ?
                ORDER BY created_at ASC
                """,
                (
                    user_id,
                    conversation_id
                )
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT
                    id,
                    conversation_id,
                    question,
                    answer,
                    confidence,
                    response_time,
                    cache_hit,
                    created_at
                FROM queries
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (
                    user_id,
                )
            ).fetchall()

    finally:

        connection.close()

    return jsonify(
        {
            "status": "success",
            "count": len(rows),
            "history": [
                dict(row)
                for row in rows
            ]
        }
    ), 200
# ============================================================
# CLEAR CACHE
# ============================================================

@rag_bp.route(
    "/clear_cache",
    methods=["POST"]
)
def clear_rag_cache():

    user_id = get_current_user_id()

    if not user_id:

        return jsonify({
            "status": "error",
            "message": "Authentication required"
        }), 401

    try:

        clear_cache()

        return jsonify({
            "status": "success",
            "message": "RAG cache cleared successfully"
        }), 200

    except Exception as error:

        print("Cache clear error:")
        print(error)

        return jsonify({
            "status": "error",
            "message": "Failed to clear cache",
            "error": str(error)
        }), 500