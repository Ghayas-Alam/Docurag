import os
import sys
import time
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

# ============================================================
# PROJECT PATHS
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
# PROJECT IMPORTS
# ============================================================

from database.database import get_db_connection

from services.hybrid_search import hybrid_search

from services.image_search import image_search

from services.cache import (
    create_cache_key,
    get_cache,
    set_cache,
    clear_cache
)

from google import genai

from api.auth_api import get_user_from_token


# ============================================================
# ROUTER
# ============================================================

rag_router = APIRouter(
    prefix="/api",
    tags=["RAG"]
)


# ============================================================
# GEMINI
# ============================================================

client = genai.Client()

MODEL_NAME = "gemini-3.1-flash-lite"


# ============================================================
# CONFIGURATION
# ============================================================

MAX_TEXT_SOURCES = 5

MAX_IMAGE_SOURCES = 3


# ============================================================
# REQUEST MODEL
# ============================================================

class AskRequest(BaseModel):

    question: str

    conversation_id: str | None = None

    # Selected document from frontend
    document_id: int | None = None


# ============================================================
# AUTHENTICATION
# ============================================================

def get_authenticated_user(
    authorization
):

    if not authorization:

        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    try:

        payload = get_user_from_token(
            authorization
        )

        user_id = int(
            payload["sub"]
        )

        return user_id

    except HTTPException:

        raise

    except Exception:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


# ============================================================
# GET USER DOCUMENT
# ============================================================

def get_user_document(
    user_id,
    document_id
):
    """
    Return the selected document only if it
    belongs to the logged-in user.
    """

    connection = get_db_connection()

    try:

        row = connection.execute(
            """
            SELECT
                id,
                original_filename,
                filename,
                processing_status
            FROM documents
            WHERE id = ?
            AND uploader_id = ?
            """,
            (
                document_id,
                user_id
            )
        ).fetchone()

        return row

    finally:

        connection.close()


# ============================================================
# GET USER DOCUMENT IDS
# ============================================================

def get_user_document_ids(
    user_id
):
    """
    Get all document IDs belonging to the
    currently logged-in user.

    This is an additional security layer.
    """

    connection = get_db_connection()

    try:

        rows = connection.execute(
            """
            SELECT id
            FROM documents
            WHERE uploader_id = ?
            """,
            (
                user_id,
            )
        ).fetchall()

        return {
            int(row["id"])
            for row in rows
        }

    finally:

        connection.close()


# ============================================================
# FILTER TEXT RESULTS BY DOCUMENT
# ============================================================

def filter_text_results_by_document(
    results,
    document_id
):

    if not results:

        return []

    filtered = []

    for result in results:

        result_document_id = result.get(
            "document_id"
        )

        if result_document_id is None:

            continue

        try:

            result_document_id = int(
                result_document_id
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        if (
            result_document_id
            == int(document_id)
        ):

            filtered.append(
                result
            )

    return filtered


# ============================================================
# FILTER IMAGE RESULTS BY DOCUMENT
# ============================================================

def filter_image_results_by_document(
    results,
    document_id
):

    if not results:

        return []

    filtered = []

    for result in results:

        result_document_id = result.get(
            "document_id"
        )

        if result_document_id is None:

            continue

        try:

            result_document_id = int(
                result_document_id
            )

        except (
            TypeError,
            ValueError
        ):

            continue

        if (
            result_document_id
            == int(document_id)
        ):

            filtered.append(
                result
            )

    return filtered


# ============================================================
# IMAGE INTENT
# ============================================================

def detect_image_intent(
    question
):
    """
    This does NOT decide what the user is asking.
    It is only used to improve image retrieval.

    Gemini still receives the complete question.
    """

    question_lower = question.lower()

    if any(
        word in question_lower
        for word in [
            "image",
            "picture",
            "photo",
            "shown",
            "visible",
            "look",
            "diagram"
        ]
    ):

        return "general"

    return "general"


# ============================================================
# FILTER IMAGE RESULTS
# ============================================================

def filter_image_results(
    results,
    question
):

    if not results:

        return []

    # Do not aggressively remove images.
    #
    # The image_search service has already ranked
    # the images according to semantic/keyword
    # relevance.
    #
    # We only keep positive-scoring results.

    filtered = []

    for result in results:

        try:

            score = float(
                result.get(
                    "score",
                    0
                )
            )

        except (
            TypeError,
            ValueError
        ):

            score = 0

        if score > 0:

            filtered.append(
                result
            )

    filtered.sort(
        key=lambda item:
            float(
                item.get(
                    "score",
                    0
                )
            ),
        reverse=True
    )

    return filtered[
        :MAX_IMAGE_SOURCES
    ]


# ============================================================
# TEXT RESULT CLEANING
# ============================================================

def prepare_text_results(
    results
):

    if not results:

        return []

    cleaned = []

    for result in results:

        score = result.get(
            "hybrid_score",
            result.get(
                "similarity",
                result.get(
                    "semantic_score",
                    0
                )
            )
        )

        try:

            score = float(
                score
            )

        except (
            TypeError,
            ValueError
        ):

            score = 0.0

        result["final_relevance"] = score

        cleaned.append(
            result
        )

    cleaned.sort(
        key=lambda item:
            item.get(
                "final_relevance",
                0
            ),
        reverse=True
    )

    return cleaned[
        :MAX_TEXT_SOURCES
    ]


# ============================================================
# BUILD TEXT CONTEXT
# ============================================================

def build_text_context(
    results
):

    if not results:

        return (
            "No relevant text was retrieved "
            "from the selected document."
        )

    context_parts = []

    for index, result in enumerate(
        results,
        start=1
    ):

        document_name = result.get(
            "document_name",
            "Unknown document"
        )

        page_number = result.get(
            "page_number",
            "Unknown"
        )

        text = result.get(
            "text",
            ""
        )

        context_parts.append(
            f"""
TEXT SOURCE {index}

Document:
{document_name}

Page:
{page_number}

Content:
{text}
"""
        )

    return "\n".join(
        context_parts
    )


# ============================================================
# BUILD IMAGE CONTEXT
# ============================================================

def build_image_context(
    results
):

    if not results:

        return (
            "No relevant image information "
            "was retrieved from the selected document."
        )

    context_parts = []

    for index, result in enumerate(
        results,
        start=1
    ):

        document_name = result.get(
            "document_name",
            "Unknown document"
        )

        page_number = result.get(
            "page_number",
            "Unknown"
        )

        description = result.get(
            "description",
            ""
        )

        extracted_text = result.get(
            "extracted_text",
            ""
        )

        objects = result.get(
            "objects",
            ""
        )

        colors = result.get(
            "colors",
            ""
        )

        orientation = result.get(
            "orientation",
            ""
        )

        context_parts.append(
            f"""
IMAGE SOURCE {index}

Document:
{document_name}

Page:
{page_number}

Description:
{description}

Extracted Text:
{extracted_text}

Objects:
{objects}

Colors:
{colors}

Orientation:
{orientation}
"""
        )

    return "\n".join(
        context_parts
    )


# ============================================================
# GET CONVERSATION HISTORY
# ============================================================

def get_conversation_history(
    user_id,
    conversation_id,
    limit=10
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
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (
                user_id,
                conversation_id,
                limit
            )
        ).fetchall()

        history = []

        for row in rows:

            history.append(
                {
                    "question":
                        row["question"],

                    "answer":
                        row["answer"]
                }
            )

        return history

    finally:

        connection.close()


# ============================================================
# BUILD HISTORY CONTEXT
# ============================================================

def build_history_context(
    history
):

    if not history:

        return (
            "No previous conversation."
        )

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
# CONFIDENCE
# ============================================================

def calculate_confidence(
    text_results,
    image_results
):

    scores = []

    for result in text_results:

        try:

            scores.append(
                float(
                    result.get(
                        "final_relevance",
                        result.get(
                            "similarity",
                            0
                        )
                    )
                )
            )

        except (
            TypeError,
            ValueError
        ):

            pass

    for result in image_results:

        try:

            scores.append(
                float(
                    result.get(
                        "score",
                        0
                    )
                )
            )

        except (
            TypeError,
            ValueError
        ):

            pass

    if not scores:

        return 0.0

    scores.sort(
        reverse=True
    )

    top_scores = scores[
        :3
    ]

    confidence = (
        sum(top_scores)
        /
        len(top_scores)
    )

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

@rag_router.post("/ask")
def ask_question(
    request: AskRequest,
    authorization: str = Header(
        default=None
    )
):

    start_time = time.time()

    # ========================================================
    # AUTH
    # ========================================================

    user_id = get_authenticated_user(
        authorization
    )

    # ========================================================
    # QUESTION VALIDATION
    # ========================================================

    question = request.question.strip()

    if not question:

        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty"
        )

    if len(question) > 2000:

        raise HTTPException(
            status_code=400,
            detail="Question is too long"
        )

    # ========================================================
    # DOCUMENT VALIDATION
    # ========================================================

    if request.document_id is None:

        raise HTTPException(
            status_code=400,
            detail=(
                "Please select a document "
                "before asking a question."
            )
        )

    document_id = int(
        request.document_id
    )

    # ========================================================
    # SECURITY CHECK
    # ========================================================

    document = get_user_document(
        user_id,
        document_id
    )

    if document is None:

        raise HTTPException(
            status_code=403,
            detail=(
                "You do not have access "
                "to this document."
            )
        )

    # ========================================================
    # DOCUMENT STATUS
    # ========================================================

    processing_status = (
        document["processing_status"]
    )

    if processing_status != "processed":

        raise HTTPException(
            status_code=400,
            detail=(
                "This document is not ready yet. "
                f"Current status: {processing_status}"
            )
        )

    # ========================================================
    # CONVERSATION
    # ========================================================

    conversation_id = (
        request.conversation_id
        or str(uuid.uuid4())
    )

    # ========================================================
    # CACHE
    # ========================================================
    #
    # IMPORTANT:
    # Document ID is part of the cache question.
    #
    # Therefore:
    #
    # Product Engineer + question
    #
    # and
    #
    # Another PDF + same question
    #
    # will NEVER share the same cached answer.
    # ========================================================

    cache_question = (
        f"[document_id:{document_id}] "
        f"{question}"
    )

    cache_key = create_cache_key(
        user_id,
        cache_question,
        conversation_id
    )

    cached_response = get_cache(
        cache_key
    )

    if cached_response is not None:

        cached_response = dict(
            cached_response
        )

        cached_response[
            "cache_hit"
        ] = True

        cached_response[
            "response_time"
        ] = round(
            time.time() -
            start_time,
            4
        )

        return cached_response

    # ========================================================
    # USER DOCUMENT SECURITY SCOPE
    # ========================================================

    user_document_ids = (
        get_user_document_ids(
            user_id
        )
    )

    if document_id not in user_document_ids:

        raise HTTPException(
            status_code=403,
            detail=(
                "Selected document does not "
                "belong to the current user."
            )
        )

    # ========================================================
    # TEXT SEARCH
    # ========================================================
    #
    # hybrid_search itself receives document_ids.
    #
    # This means FAISS + keyword search are scoped
    # to the selected document.
    # ========================================================

    try:

        text_results = hybrid_search(
            question,
            top_k=10,
            document_ids={
                document_id
            }
        )

    except TypeError:

        # Fallback for an older hybrid_search
        # implementation.
        #
        # We still filter the results immediately
        # afterwards.

        text_results = hybrid_search(
            question,
            top_k=20
        )

    except Exception as error:

        print(
            "Hybrid search error:"
        )

        print(
            error
        )

        text_results = []

    # ========================================================
    # SECOND SECURITY FILTER
    # ========================================================

    text_results = (
        filter_text_results_by_document(
            text_results,
            document_id
        )
    )

    # ========================================================
    # PREPARE TEXT RESULTS
    # ========================================================

    text_results = prepare_text_results(
        text_results
    )

    # ========================================================
    # IMAGE SEARCH
    # ========================================================

    try:

        image_results = image_search(
            question,
            top_k=10
        )

    except Exception as error:

        print(
            "Image search error:"
        )

        print(
            error
        )

        image_results = []

    # ========================================================
    # DOCUMENT SECURITY FOR IMAGES
    # ========================================================

    image_results = (
        filter_image_results_by_document(
            image_results,
            document_id
        )
    )

    # ========================================================
    # IMAGE RELEVANCE
    # ========================================================

    image_results = filter_image_results(
        image_results,
        question
    )

    # ========================================================
    # CONTEXT
    # ========================================================

    text_context = build_text_context(
        text_results
    )

    image_context = build_image_context(
        image_results
    )

    # ========================================================
    # HISTORY
    # ========================================================

    history = get_conversation_history(
        user_id,
        conversation_id
    )

    history_context = build_history_context(
        history
    )

    # ========================================================
    # GEMINI PROMPT
    # ========================================================
    #
    # NO QUESTION TYPES ARE HARDCODED.
    #
    # Gemini receives the actual user question and
    # retrieved document context.
    # ========================================================

    prompt = f"""
You are DocuRAG, an AI-powered document and image
question-answering assistant.

The user has selected ONE document.

You must answer the user's question using the
retrieved information from that selected document.

The user may ask ANY natural-language question.

Understand the user's question semantically and answer
appropriately based on the available context.

IMPORTANT RULES:

1. Use the retrieved document context as the primary
   source of truth.

2. Do not invent facts that are not supported by the
   retrieved context.

3. Do not use information from any other document.

4. If the retrieved context does not contain enough
   information to answer the question, say clearly that
   the information could not be found in the selected
   document.

5. Do not mention irrelevant sources.

6. If the question is about an image, use the image
   information when it is relevant.

7. If the question requires combining information from
   multiple retrieved sections, combine them logically.

8. Conversation history may be used to understand
   references such as "it", "that", "the previous section",
   etc., but factual answers must remain grounded in the
   selected document.

9. Do not answer from general knowledge when the answer
   is not supported by the selected document.

10. Give a clear, natural-language answer.

USER QUESTION:
{question}

SELECTED DOCUMENT:
{document["original_filename"]}

TEXT CONTEXT:
{text_context}

IMAGE CONTEXT:
{image_context}

CONVERSATION HISTORY:
{history_context}

Now answer the user's question.
"""

    # ========================================================
    # GEMINI
    # ========================================================

    try:

        interaction = client.interactions.create(
            model=MODEL_NAME,
            input=prompt
        )

        answer = interaction.output_text

    except Exception as error:

        error_text = str(
            error
        )

        print(
            "Gemini error:"
        )

        print(
            error_text
        )

        if (
            "429" in error_text
            or
            "RESOURCE_EXHAUSTED"
            in error_text
        ):

            raise HTTPException(
                status_code=429,
                detail=(
                    "Gemini API rate limit reached. "
                    "Please try again later."
                )
            )

        raise HTTPException(
            status_code=500,
            detail=(
                "AI generation failed: "
                f"{error_text}"
            )
        )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    confidence = calculate_confidence(
        text_results,
        image_results
    )

    # ========================================================
    # RESPONSE TIME
    # ========================================================

    response_time = round(
        time.time() -
        start_time,
        4
    )

    # ========================================================
    # SAVE QUERY
    # ========================================================

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

        # ----------------------------------------------------
        # SAVE TEXT SOURCES
        # ----------------------------------------------------

        for rank, source in enumerate(
            text_results,
            start=1
        ):

            similarity = source.get(
                "final_relevance",
                source.get(
                    "similarity",
                    0
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
                        "chunk_id",
                        source.get(
                            "id"
                        )
                    ),

                    float(
                        similarity
                    ),

                    source.get(
                        "page_number"
                    ),

                    source.get(
                        "text",
                        source.get(
                            "chunk_text",
                            ""
                        )
                    ),

                    None,

                    rank
                )
            )

        connection.commit()

    finally:

        connection.close()

    # ========================================================
    # RESPONSE SOURCES
    # ========================================================

    sources = []

    for rank, source in enumerate(
        text_results,
        start=1
    ):

        sources.append(
            {
                "document_id":
                    source.get(
                        "document_id"
                    ),

                "document_name":
                    source.get(
                        "document_name",
                        document[
                            "original_filename"
                        ]
                    ),

                "page_number":
                    source.get(
                        "page_number"
                    ),

                "chunk_id":
                    source.get(
                        "chunk_id",
                        source.get(
                            "id"
                        )
                    ),

                "similarity":
                    round(
                        float(
                            source.get(
                                "final_relevance",
                                source.get(
                                    "similarity",
                                    0
                                )
                            )
                        ),
                        4
                    ),

                "rank":
                    rank
            }
        )

    # ========================================================
    # IMAGE SOURCES
    # ========================================================

    image_sources = []

    for image in image_results:

        image_sources.append(
            {
                "document_id":
                    image.get(
                        "document_id"
                    ),

                "document_name":
                    image.get(
                        "document_name",
                        document[
                            "original_filename"
                        ]
                    ),

                "image_id":
                    image.get(
                        "image_id"
                    ),

                "page_number":
                    image.get(
                        "page_number"
                    ),

                "score":
                    round(
                        float(
                            image.get(
                                "score",
                                0
                            )
                        ),
                        4
                    ),

                "description":
                    image.get(
                        "description",
                        ""
                    ),

                "extracted_text":
                    image.get(
                        "extracted_text",
                        ""
                    )
            }
        )

    # ========================================================
    # FINAL RESPONSE
    # ========================================================

    response = {

        "status":
            "success",

        "question":
            question,

        "answer":
            answer,

        "confidence":
            confidence,

        "conversation_id":
            conversation_id,

        "query_id":
            query_id,

        "cache_hit":
            False,

        "response_time":
            response_time,

        "selected_document_id":
            document_id,

        "selected_document":
            document[
                "original_filename"
            ],

        "sources":
            sources,

        "image_sources":
            image_sources
    }

    # ========================================================
    # CACHE
    # ========================================================

    set_cache(
        cache_key,
        response
    )

    return response


# ============================================================
# HISTORY
# ============================================================

@rag_router.get("/history")
def get_history(
    authorization: str = Header(
        default=None
    )
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

        return {

            "status":
                "success",

            "count":
                len(rows),

            "history": [
                dict(row)
                for row in rows
            ]
        }

    finally:

        connection.close()


# ============================================================
# NEW CHAT
# ============================================================

@rag_router.post("/new_chat")
def new_chat(
    authorization: str = Header(
        default=None
    )
):

    get_authenticated_user(
        authorization
    )

    conversation_id = str(
        uuid.uuid4()
    )

    return {

        "status":
            "success",

        "conversation_id":
            conversation_id,

        "message":
            "New conversation created"
    }


# ============================================================
# CLEAR CACHE
# ============================================================

@rag_router.post("/clear_cache")
def clear_rag_cache(
    authorization: str = Header(
        default=None
    )
):

    get_authenticated_user(
        authorization
    )

    clear_cache()

    return {

        "status":
            "success",

        "message":
            "RAG cache cleared successfully"
    }