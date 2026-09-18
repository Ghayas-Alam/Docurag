import os
import sys
import pickle

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# PROJECT PATH
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
# DATABASE
# ============================================================

from database.database import get_db_connection


# ============================================================
# EMBEDDING MODEL
# ============================================================

MODEL_NAME = "all-MiniLM-L6-v2"

print("Loading embedding model...")

model = SentenceTransformer(
    MODEL_NAME
)

# New method name
try:
    EMBEDDING_DIMENSION = (
        model.get_embedding_dimension()
    )
except AttributeError:
    EMBEDDING_DIMENSION = (
        model.get_sentence_embedding_dimension()
    )

print(
    f"Embedding dimension: {EMBEDDING_DIMENSION}"
)


# ============================================================
# FAISS FILES
# ============================================================

INDEX_PATH = os.path.join(
    PROJECT_ROOT,
    "docurag.index"
)

CHUNKS_PATH = os.path.join(
    PROJECT_ROOT,
    "chunks.pkl"
)


# ============================================================
# BUILD FAISS INDEX
# ============================================================

def build_index():

    print()
    print("=" * 60)
    print("Building FAISS index...")
    print("=" * 60)

    connection = get_db_connection()

    try:

        rows = connection.execute(
            """
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
            ORDER BY
                dc.document_id,
                dc.page_number,
                dc.position
            """
        ).fetchall()

    finally:

        connection.close()

    # ========================================================
    # NO CHUNKS
    # ========================================================

    if not rows:

        index = faiss.IndexFlatIP(
            EMBEDDING_DIMENSION
        )

        faiss.write_index(
            index,
            INDEX_PATH
        )

        with open(
            CHUNKS_PATH,
            "wb"
        ) as file:

            pickle.dump(
                [],
                file
            )

        print(
            "No processed chunks found."
        )

        return {
            "status": "success",
            "chunks": 0,
            "dimension": EMBEDDING_DIMENSION
        }

    # ========================================================
    # PREPARE TEXT + METADATA
    # ========================================================

    texts = []
    metadata = []

    for row in rows:

        text = row["text"] or ""

        if not text.strip():
            continue

        texts.append(
            text
        )

        metadata.append(
            {
                "chunk_id": row["id"],
                "document_id": row["document_id"],
                "document_name": row["original_filename"],
                "page_number": row["page_number"],
                "position": row["position"],
                "text": text
            }
        )

    # ========================================================
    # STILL NO VALID TEXT
    # ========================================================

    if not texts:

        index = faiss.IndexFlatIP(
            EMBEDDING_DIMENSION
        )

        faiss.write_index(
            index,
            INDEX_PATH
        )

        with open(
            CHUNKS_PATH,
            "wb"
        ) as file:

            pickle.dump(
                [],
                file
            )

        return {
            "status": "success",
            "chunks": 0,
            "dimension": EMBEDDING_DIMENSION
        }

    # ========================================================
    # GENERATE EMBEDDINGS
    # ========================================================

    print(
        f"Generating embeddings for {len(texts)} chunks..."
    )

    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True
    )

    embeddings = embeddings.astype(
        "float32"
    )

    # Normalize for cosine similarity
    faiss.normalize_L2(
        embeddings
    )

    # ========================================================
    # CREATE FAISS INDEX
    # ========================================================

    index = faiss.IndexFlatIP(
        EMBEDDING_DIMENSION
    )

    index.add(
        embeddings
    )

    # ========================================================
    # SAVE INDEX
    # ========================================================

    faiss.write_index(
        index,
        INDEX_PATH
    )

    with open(
        CHUNKS_PATH,
        "wb"
    ) as file:

        pickle.dump(
            metadata,
            file
        )

    print(
        f"FAISS index updated: {len(metadata)} chunks"
    )

    print(
        f"Index saved: {INDEX_PATH}"
    )

    return {
        "status": "success",
        "chunks": len(metadata),
        "dimension": EMBEDDING_DIMENSION
    }


# ============================================================
# LOAD FAISS INDEX
# ============================================================

def load_index():

    if not os.path.exists(
        INDEX_PATH
    ):

        print(
            "FAISS index not found. Building index..."
        )

        build_index()

    index = faiss.read_index(
        INDEX_PATH
    )

    # --------------------------------------------------------
    # Load metadata
    # --------------------------------------------------------

    if os.path.exists(
        CHUNKS_PATH
    ):

        with open(
            CHUNKS_PATH,
            "rb"
        ) as file:

            metadata = pickle.load(
                file
            )

    else:

        metadata = []

    return (
        index,
        metadata
    )


# ============================================================
# SEMANTIC SEARCH
# ============================================================

def search_similar(
    question,
    top_k=5
):

    index, metadata = load_index()

    # --------------------------------------------------------
    # Empty index
    # --------------------------------------------------------

    if index.ntotal == 0:

        return []

    # --------------------------------------------------------
    # Generate query embedding
    # --------------------------------------------------------

    query_embedding = model.encode(
        [question],
        convert_to_numpy=True
    )

    query_embedding = query_embedding.astype(
        "float32"
    )

    # Normalize
    faiss.normalize_L2(
        query_embedding
    )

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    actual_k = min(
        top_k,
        index.ntotal
    )

    scores, indices = index.search(
        query_embedding,
        actual_k
    )

    results = []

    # --------------------------------------------------------
    # Build results
    # --------------------------------------------------------

    for score, index_position in zip(
        scores[0],
        indices[0]
    ):

        if index_position < 0:
            continue

        if index_position >= len(metadata):
            continue

        item = metadata[
            index_position
        ].copy()

        item["semantic_score"] = float(
            score
        )

        # Compatibility with existing code
        item["similarity"] = float(
            score
        )

        results.append(
            item
        )

    return results


# ============================================================
# COMPATIBILITY FUNCTION
# ============================================================
#
# hybrid_search.py currently imports:
#
# from services.vector_store import search_similar_chunks
#
# Therefore this wrapper is required.
# ============================================================

def search_similar_chunks(
    question,
    top_k=5
):

    return search_similar(
        question,
        top_k=top_k
    )


# ============================================================
# SEARCH INSIDE ONE DOCUMENT
# ============================================================

def search_by_document(
    question,
    document_id,
    top_k=5
):

    # Search more results first because we later
    # filter by document ID.

    results = search_similar(
        question,
        top_k=max(
            top_k * 5,
            20
        )
    )

    filtered_results = []

    for result in results:

        if result["document_id"] == document_id:

            filtered_results.append(
                result
            )

    return filtered_results[
        :top_k
    ]


# ============================================================
# REBUILD INDEX
# ============================================================

def rebuild_index():

    return build_index()


# ============================================================
# INDEX INFORMATION
# ============================================================

def get_index_info():

    if not os.path.exists(
        INDEX_PATH
    ):

        return {
            "exists": False,
            "vectors": 0,
            "metadata": 0,
            "dimension": EMBEDDING_DIMENSION
        }

    index, metadata = load_index()

    return {
        "exists": True,
        "vectors": index.ntotal,
        "metadata": len(metadata),
        "dimension": (
            index.d
            if hasattr(index, "d")
            else EMBEDDING_DIMENSION
        )
    }


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("DOCURAG VECTOR STORE TEST")
    print("=" * 60)

    print()
    print("Building index...")

    result = build_index()

    print()
    print("Build result:")
    print(result)

    print()
    print("Index information:")

    info = get_index_info()

    print(info)

    print()
    print("Testing semantic search...")

    question = "What is Python?"

    results = search_similar_chunks(
        question,
        top_k=5
    )

    print()
    print(
        f"Question: {question}"
    )

    print()

    for rank, result in enumerate(
        results,
        start=1
    ):

        print(
            f"Rank {rank}: "
            f"{result['document_name']} | "
            f"Page {result['page_number']} | "
            f"Score {result['similarity']:.4f}"
        )

    print()
    print("Vector store test completed.")