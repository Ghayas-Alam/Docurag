
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from google.genai.types import HttpOptions, HttpRetryOptions

load_dotenv()

MODEL_NAME = "gemini-3.1-flash-lite"
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not configured. "
        "Please add it to the environment."
    )


client = genai.Client(
    api_key=API_KEY,
    http_options=HttpOptions(
        retry_options=HttpRetryOptions(
            attempts=1
        )
    )
)


def normal_chat(message: str) -> str:
    """
    Send a normal chat message directly to Gemini.

    This is used when the user has not selected a document.
    """

    if not message or not message.strip():
        raise ValueError("Message cannot be empty.")

    user_message = message.strip()

    max_retries = 3
    retry_delays = [3, 6, 12]

    for attempt in range(max_retries):
        try:
            print(
                f"[Normal Chat] Gemini request "
                f"attempt {attempt + 1}/{max_retries}"
            )

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=user_message
            )

            if not response or not response.text:
                raise RuntimeError(
                    "Gemini returned an empty response."
                )

            print("[Normal Chat] Gemini response received.")

            return response.text

        except errors.ServerError as e:
            print(
                f"[Normal Chat] Gemini server error "
                f"(attempt {attempt + 1}/{max_retries}): {e}"
            )

            # Gemini 503 = temporary server/model availability issue.
            if attempt < max_retries - 1:
                delay = retry_delays[attempt]

                print(
                    f"[Normal Chat] Gemini temporarily unavailable. "
                    f"Retrying in {delay} seconds..."
                )

                time.sleep(delay)

            else:
                print(
                    "[Normal Chat] Gemini unavailable "
                    "after all retry attempts."
                )

                raise RuntimeError(
                    "Gemini is temporarily busy. "
                    "Please try again in a few moments."
                )

        except errors.ClientError as e:
            status_code = getattr(e, "status_code", None)

            if status_code == 429:
                print(
                    f"[Normal Chat] Gemini rate limit "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )

                if attempt < max_retries - 1:
                    delay = retry_delays[attempt]

                    print(
                        f"[Normal Chat] Rate limit reached. "
                        f"Retrying in {delay} seconds..."
                    )

                    time.sleep(delay)

                else:
                    print(
                        "[Normal Chat] Gemini rate limit persisted "
                        "after all retry attempts."
                    )

                    raise RuntimeError(
                        "Gemini rate limit reached. "
                        "Please try again later."
                    )

            else:
                print(
                    f"[Normal Chat] Gemini client error "
                    f"(status {status_code}): {e}"
                )

                raise RuntimeError(
                    "Gemini could not process the request."
                )

        except Exception as e:
            print("[Normal Chat] Unexpected error:")
            print(f"{type(e).__name__}: {e}")

            raise RuntimeError(
                "An unexpected error occurred while "
                "processing your message."
            )

    raise RuntimeError("Gemini request failed.")

