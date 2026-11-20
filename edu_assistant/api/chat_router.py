"""注册客服会话与消息接口，适配 JSON 和 SSE。"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from edu_assistant.api.dependencies import ServiceDependency, User
from edu_assistant.api.schemas import Identifier, Message, NewSession
from edu_assistant.api.streaming import events
from edu_assistant.domain.turn import Accepted

router = APIRouter(prefix="/api/v1/chat/sessions")
Limit = Annotated[int, Query(ge=1, le=100)]
ExpectedVersion = Annotated[int, Query(alias="expectedStateVersion", ge=0, le=2**63 - 1)]


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


@router.post("", status_code=201)
async def create(service: ServiceDependency, body: NewSession, user_id: User):
    return ok(await service.create_session(user_id, body.title))


@router.get("")
async def list_sessions(service: ServiceDependency, user_id: User, cursor: Identifier | None = None, limit: Limit = 20):
    return ok(await service.list_sessions(user_id, cursor, limit))


@router.get("/{session_id}/state")
async def state(service: ServiceDependency, session_id: Identifier, user_id: User):
    return ok(await service.state(user_id, session_id))


@router.delete("/{session_id}")
async def delete_session(service: ServiceDependency, session_id: Identifier, user_id: User,
                         expected_state_version: ExpectedVersion):
    return ok(await service.delete_session(user_id, session_id, expected_state_version))


@router.get("/{session_id}/messages")
async def history(service: ServiceDependency, session_id: Identifier, user_id: User,
                  cursor: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0, limit: Limit = 20,
                  client_message_id: Annotated[Identifier | None, Query(alias="clientMessageId")] = None):
    return ok(await service.history(user_id, session_id, cursor, limit, client_message_id))


@router.delete("/{session_id}/messages")
async def clear_messages(service: ServiceDependency, session_id: Identifier, user_id: User,
                         expected_state_version: ExpectedVersion):
    return ok(await service.clear_messages(user_id, session_id, expected_state_version))


@router.post("/{session_id}/messages")
async def send(service: ServiceDependency, session_id: Identifier, body: Message, user_id: User):
    payload = body.model_dump(exclude={"stream"}, exclude_none=True, mode="json")
    accepted = await service.accept(user_id, session_id, payload)
    task = service.start(user_id, accepted, payload) if isinstance(accepted, Accepted) else None
    if body.stream:
        return StreamingResponse(events(accepted, task), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return ok(await asyncio.shield(task) if task else accepted)
