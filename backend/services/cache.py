import time
import threading


# ==========================================
# CACHE CONFIGURATION
# ==========================================

CACHE_TTL = 3600       # 1 hour
MAX_CACHE_SIZE = 500   # Maximum cached responses


# ==========================================
# CACHE STORAGE
# ==========================================

_cache = {}

_cache_lock = threading.Lock()


# ==========================================
# CREATE CACHE KEY
# ==========================================

def create_cache_key(
    user_id,
    question,
    conversation_id
):

    normalized_question = (
        question
        .strip()
        .lower()
    )

    return (
        f"{user_id}:"
        f"{conversation_id}:"
        f"{normalized_question}"
    )


# ==========================================
# GET FROM CACHE
# ==========================================

def get_cache(key):

    with _cache_lock:

        item = _cache.get(key)

        if item is None:

            return None

        # ----------------------------------
        # Check expiration
        # ----------------------------------

        current_time = time.time()

        if (
            current_time - item["timestamp"]
            > CACHE_TTL
        ):

            del _cache[key]

            return None

        return item["data"]


# ==========================================
# SAVE TO CACHE
# ==========================================

def set_cache(
    key,
    data
):

    with _cache_lock:

        # ----------------------------------
        # Remove oldest item if full
        # ----------------------------------

        if len(_cache) >= MAX_CACHE_SIZE:

            oldest_key = min(
                _cache,
                key=lambda k:
                    _cache[k]["timestamp"]
            )

            del _cache[
                oldest_key
            ]

        _cache[key] = {

            "timestamp":
                time.time(),

            "data":
                data

        }


# ==========================================
# DELETE ONE CACHE ENTRY
# ==========================================

def delete_cache(key):

    with _cache_lock:

        if key in _cache:

            del _cache[key]

            return True

        return False


# ==========================================
# CLEAR ALL CACHE
# ==========================================

def clear_cache():

    with _cache_lock:

        count = len(_cache)

        _cache.clear()

        return count


# ==========================================
# CACHE INFORMATION
# ==========================================

def get_cache_info():

    with _cache_lock:

        current_time = time.time()

        # Remove expired entries

        expired_keys = [

            key

            for key, item
            in _cache.items()

            if (
                current_time
                - item["timestamp"]
            ) > CACHE_TTL

        ]

        for key in expired_keys:

            del _cache[key]

        return {

            "size":
                len(_cache),

            "max_size":
                MAX_CACHE_SIZE,

            "ttl_seconds":
                CACHE_TTL

        }


# ==========================================
# TEST
# ==========================================

if __name__ == "__main__":

    print(
        "\n=============================="
    )

    print(
        "DOCURAG CACHE TEST"
    )

    print(
        "=============================="
    )

    key = create_cache_key(
        1,
        "What is Python?",
        "conversation-1"
    )

    print(
        "\nCache key:"
    )

    print(
        key
    )

    print(
        "\nBefore storing:"
    )

    print(
        get_cache(key)
    )

    test_data = {

        "answer":
            "Python is a programming language.",

        "confidence":
            0.85

    }

    set_cache(
        key,
        test_data
    )

    print(
        "\nAfter storing:"
    )

    print(
        get_cache(key)
    )

    print(
        "\nCache information:"
    )

    print(
        get_cache_info()
    )

    clear_cache()

    print(
        "\nAfter clearing:"
    )

    print(
        get_cache(key)
    )