from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_service import normal_chat


chat_router = APIRouter(
    prefix="/chat",
    tags=["Normal Chat"]
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str


@chat_router.post("/normal", response_model=ChatResponse)
def normal_chat_endpoint(request: ChatRequest):

    try:
        answer = normal_chat(request.message)

        return {
            "answer": answer
        }

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:
        print("========================================")
        print("NORMAL CHAT ERROR:")
        print(type(e).__name__)
        print(str(e))
        print("========================================")

        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Please try again."
        )