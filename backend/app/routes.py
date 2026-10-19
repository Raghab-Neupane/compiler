#using the schemas to receive the frontend code pass.

from asyncio import coroutines
from fastapi.routing import APIRouter
from fastapi import FastAPI
from app.schemas import CodeRequest,CodeResponse

import uuid

router = APIRouter()

@router.post("/execute", response_model=CodeResponse)
def receive_code(request : CodeRequest):
    return CodeResponse(
        p_id = str(uuid.uuid4()),
        message="Code Executed Successfully",
        language=request.language,
        output="This is a dummy output"
    )