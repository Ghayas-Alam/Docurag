import os
import sys
import re

# ==========================================
# PROJECT PATHS
# ==========================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

BACKEND_ROOT = os.path.join(
    PROJECT_ROOT,
    "backend"
)

sys.path.append(PROJECT_ROOT)
sys.path.append(BACKEND_ROOT)


from database.database import get_db_connection
from services.vector_store import search_similar_chunks


# ==========================================
# STOP WORDS
# ==========================================

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your"
}


# ==========================================
# TOKENIZATION
# ==========================================

def tokenize(text):
    """
    Convert text into meaningful lowercase words.
    Common English stop words are removed.
    """

    words = re.findall(
        r"\b[a-zA-Z0-9]+\b",
        text.lower()
    )

    meaningful_words = [
        word
        for word in words
        if word not in STOP_WORDS
    ]

    return set(
        meaningful_words
    )


# ==========================================
# DOCUMENT ID NORMALIZER
# ==========================================

def normalize_document_ids(
    document_ids
):
    """
    Convert document IDs into a set of integers.

    Example:
        [1, 2, 3] -> {1, 2, 3}
        {1, 2}    -> {1, 2}
        None      -> None
    """

    if document_ids is None:

        return None

    if isinstance(
        document_ids,
        (int, str)
    ):

        document_ids = [
            document_ids
        ]

    normalized = set()

    for document_id in document_ids:

        try:

            normalized.add(
                int(document_id)
            )

        except (
            TypeError,
            ValueError
        ):

            continue

    return normalized


# ==========================================
# KEYWORD SEARCH
# ==========================================

def keyword_search(
    question,
    top_k=5,
    document_ids=None
):
    """
    Keyword-based search.

    If document_ids are provided,
    only those documents are searched.
    """

    question_words = tokenize(
        question
    )

    if not question_words:

        return []

    document_ids = normalize_document_ids(
        document_ids
    )

    # --------------------------------------
    # If explicit document scope is empty
    # --------------------------------------

    if document_ids is not None and not document_ids:

        return []

    connection = get_db_connection()

    try:

        # ----------------------------------
        # Base query
        # ----------------------------------

        sql = """
            SELECT
                dc.id,
                dc.document_id,
                dc.text,
                dc.page_number,
                dc.position,
                d.original_filename
            FROM document_chunks dc

            INNER JOIN documents d
                ON dc.document_id = d.id

            WHERE d.processing_status = 'processed'
        """

        parameters = []

        # ----------------------------------
        # Document filtering
        # ----------------------------------

        if document_ids is not None:

            placeholders = ",".join(
                "?"
                for _ in document_ids
            )

            sql += f"""
                AND dc.document_id
                IN ({placeholders})
            """

            parameters.extend(
                sorted(
                    document_ids
                )
            )

        # ----------------------------------
        # Ordering
        # ----------------------------------

        sql += """
            ORDER BY
                dc.document_id,
                dc.page_number,
                dc.position
        """

        chunks = connection.execute(
            sql,
            parameters
        ).fetchall()

        results = []

        for chunk in chunks:

            chunk_words = tokenize(
                chunk["text"]
            )

            matched_words = (
                question_words.intersection(
                    chunk_words
                )
            )

            if not matched_words:

                continue

            keyword_score = (
                len(matched_words)
                /
                len(question_words)
            )

            results.append({

                "chunk_id":
                    chunk["id"],

                "document_id":
                    chunk["document_id"],

                "document_name":
                    chunk["original_filename"],

                "text":
                    chunk["text"],

                "page_number":
                    chunk["page_number"],

                "position":
                    chunk["position"],

                "keyword_score":
                    float(
                        keyword_score
                    )

            })

        results.sort(
            key=lambda x:
                x["keyword_score"],
            reverse=True
        )

        return results[
            :top_k
        ]

    finally:

        connection.close()


# ==========================================
# HYBRID SEARCH
# ==========================================

def hybrid_search(
    question,
    top_k=5,
    document_ids=None
):
    """
    Hybrid semantic + keyword search.

    document_ids:
        If provided, only those documents
        are allowed in the final results.

    Example:
        hybrid_search(
            "What is this document about?",
            top_k=10,
            document_ids=[3]
        )
    """

    document_ids = normalize_document_ids(
        document_ids
    )

    # --------------------------------------
    # Empty document scope
    # --------------------------------------

    if document_ids is not None and not document_ids:

        return []

    # --------------------------------------
    # Semantic Search
    # --------------------------------------
    #
    # The FAISS index is global.
    #
    # Therefore retrieve a larger candidate
    # set first and filter it by document_id.
    #
    # This prevents a relevant chunk from
    # being lost simply because another
    # document ranked higher globally.
    # --------------------------------------

    semantic_top_k = max(
        top_k * 20,
        100
    )

    semantic_results = search_similar_chunks(
        question,
        top_k=semantic_top_k
    )

    # --------------------------------------
    # Filter semantic results
    # --------------------------------------

    if document_ids is not None:

        semantic_results = [

            result

            for result in semantic_results

            if result.get(
                "document_id"
            ) is not None

            and int(
                result["document_id"]
            )
            in document_ids

        ]

    # --------------------------------------
    # Keep only requested amount
    # --------------------------------------

    semantic_results = semantic_results[
        :top_k
    ]

    # --------------------------------------
    # Keyword Search
    # --------------------------------------

    keyword_results = keyword_search(
        question,
        top_k=top_k,
        document_ids=document_ids
    )

    # --------------------------------------
    # Combine Results
    # --------------------------------------

    combined = {}

    # --------------------------------------
    # Add Semantic Results
    # --------------------------------------

    for result in semantic_results:

        chunk_id = result.get(
            "chunk_id"
        )

        if chunk_id is None:

            continue

        combined[chunk_id] = {

            "chunk_id":
                chunk_id,

            "document_id":
                result.get(
                    "document_id"
                ),

            "document_name":
                result.get(
                    "document_name",
                    "Unknown"
                ),

            "text":
                result.get(
                    "text",
                    ""
                ),

            "page_number":
                result.get(
                    "page_number"
                ),

            "position":
                result.get(
                    "position",
                    0
                ),

            "semantic_score":
                float(
                    result.get(
                        "similarity",
                        0
                    )
                ),

            "keyword_score":
                0.0

        }

    # --------------------------------------
    # Add Keyword Results
    # --------------------------------------

    for result in keyword_results:

        chunk_id = result.get(
            "chunk_id"
        )

        if chunk_id is None:

            continue

        if chunk_id not in combined:

            combined[chunk_id] = {

                "chunk_id":
                    chunk_id,

                "document_id":
                    result.get(
                        "document_id"
                    ),

                "document_name":
                    result.get(
                        "document_name",
                        "Unknown"
                    ),

                "text":
                    result.get(
                        "text",
                        ""
                    ),

                "page_number":
                    result.get(
                        "page_number"
                    ),

                "position":
                    result.get(
                        "position",
                        0
                    ),

                "semantic_score":
                    0.0,

                "keyword_score":
                    float(
                        result.get(
                            "keyword_score",
                            0
                        )
                    )

            }

        else:

            combined[chunk_id][
                "keyword_score"
            ] = float(
                result.get(
                    "keyword_score",
                    0
                )
            )

            combined[chunk_id][
                "document_name"
            ] = result.get(
                "document_name",
                combined[chunk_id][
                    "document_name"
                ]
            )

    # --------------------------------------
    # Calculate Hybrid Score
    # --------------------------------------

    for result in combined.values():

        semantic_score = float(
            result.get(
                "semantic_score",
                0
            )
        )

        keyword_score = float(
            result.get(
                "keyword_score",
                0
            )
        )

        result["hybrid_score"] = (
            0.7 * semantic_score
            +
            0.3 * keyword_score
        )

        # Existing RAG code expects
        # "similarity"

        result["similarity"] = (
            result["hybrid_score"]
        )

    # --------------------------------------
    # Final Document Safety Filter
    # --------------------------------------
    #
    # This is intentionally repeated here.
    # Even if something unexpected happens
    # in the search layer, an out-of-scope
    # document cannot reach the final result.
    # --------------------------------------

    final_results = []

    for result in combined.values():

        if document_ids is not None:

            try:

                result_document_id = int(
                    result.get(
                        "document_id"
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            if (
                result_document_id
                not in document_ids
            ):

                continue

        final_results.append(
            result
        )

    # --------------------------------------
    # Sort
    # --------------------------------------

    final_results.sort(
        key=lambda x:
            x.get(
                "hybrid_score",
                0
            ),
        reverse=True
    )

    return final_results[
        :top_k
    ]


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print(
        "\n=============================="
    )

    print(
        "HYBRID SEARCH TEST"
    )

    print(
        "=============================="
    )

    question = (
        "What is the average speed in Q20?"
    )

    print(
        f"\nQuestion: {question}"
    )

    results = hybrid_search(
        question,
        top_k=5,
        document_ids={document_id}
    )

    print(
        "\nHybrid Search Results:"
    )

    for rank, result in enumerate(
        results,
        start=1
    ):

        print(
            "\n------------------------------"
        )

        print(
            f"Rank: {rank}"
        )

        print(
            f"Document ID: "
            f"{result['document_id']}"
        )

        print(
            f"Document: "
            f"{result['document_name']}"
        )

        print(
            f"Page: "
            f"{result['page_number']}"
        )

        print(
            f"Semantic Score: "
            f"{result['semantic_score']:.4f}"
        )

        print(
            f"Keyword Score: "
            f"{result['keyword_score']:.4f}"
        )

        print(
            f"Hybrid Score: "
            f"{result['hybrid_score']:.4f}"
        )

        print("\nText:")

        print(
            result["text"][:300]
        )