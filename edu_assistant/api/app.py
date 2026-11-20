"""组装 FastAPI 应用、资源生命周期和统一错误处理。"""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from edu_assistant.api.chat_router import router
from edu_assistant.conf.config import Settings
from edu_assistant.domain.errors import ChatError
from edu_assistant.engine.builder import build_dialogue
from edu_assistant.repository.chat_repository import Repository
from edu_assistant.service.dialogue_service import DialogueService

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    if not settings.chat_database_url.startswith("mysql+pymysql://"):
        raise RuntimeError("请在 .env 填写 CHAT_DATABASE_URL（mysql+pymysql://）")
    engine = create_engine(settings.chat_database_url, pool_pre_ping=True, hide_parameters=True,
                           connect_args={"connect_timeout": 5, "read_timeout": 10, "write_timeout": 10})
    async with httpx.AsyncClient(base_url=settings.edu_data_base_url, timeout=5) as client:
        dialogue = build_dialogue(settings, client)
        app.state.service = DialogueService(Repository(engine), dialogue)
        app.state.settings = settings
        try:
            yield
        finally:
            await asyncio.gather(*app.state.service.pending, return_exceptions=True)
            await run_in_threadpool(engine.dispose)


app = FastAPI(title="教育智能客服 v2", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(ChatError)
async def handle_chat_error(request, exc):
    return JSONResponse({"code": exc.code, "message": str(exc), "data": None}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def handle_invalid(request, exc):
    return JSONResponse({"code": "INVALID_REQUEST", "message": "请求字段或格式无效", "data": None}, status_code=422)


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(request, exc):
    log.warning("chat persistence unavailable kind=%s", type(exc).__name__)
    return JSONResponse({"code": "CHAT_STORAGE_UNAVAILABLE", "message": "会话存储暂不可用", "data": None}, status_code=503)
