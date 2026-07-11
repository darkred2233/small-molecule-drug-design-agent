"""
Chat API路由 - 对话接口
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from medagent.db.session import get_db
from medagent.llm import LLMMessage, get_llm_client

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    provider: str = "qwen"
    model: str | None = None
    temperature: float = 0.7
    stream: bool = False


class ChatResponse(BaseModel):
    response: str
    model: str
    provider: str
    tokens: int


@router.post("/completions", response_model=ChatResponse)
def chat_completion(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """聊天补全"""
    llm_client = get_llm_client()

    messages = [
        LLMMessage(role="user", content=request.message)
    ]

    try:
        response = llm_client.complete(
            messages=messages,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
        )

        return ChatResponse(
            response=response.content,
            model=response.model,
            provider=response.provider,
            tokens=response.total_tokens,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: Session = Depends(get_db),
):
    """流式聊天"""
    from fastapi.responses import StreamingResponse

    llm_client = get_llm_client()

    messages = [
        LLMMessage(role="user", content=request.message)
    ]

    async def generate():
        try:
            async for chunk in llm_client.async_stream(
                messages=messages,
                provider=request.provider,
                model=request.model,
                temperature=request.temperature,
            ):
                yield f"data: {chunk.content}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
