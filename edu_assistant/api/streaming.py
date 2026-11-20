"""以 SSE 交付已持久化的对话结果。"""

import asyncio
import json

from sqlalchemy.exc import SQLAlchemyError

from edu_assistant.domain.errors import ChatError
from edu_assistant.domain.turn import Accepted


def event(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def events(accepted, task):
    if isinstance(accepted, Accepted):
        yield event("meta", {"turnId": accepted.turn_id, "traceId": accepted.trace_id})
        yield event("progress", {"message": "正在处理…"})
        try:
            result = await asyncio.shield(task)
        except ChatError as exc:
            yield event("error", {"code": exc.code, "message": str(exc), "traceId": accepted.trace_id})
            return
        except SQLAlchemyError:
            yield event("error", {"code": "CHAT_STORAGE_UNAVAILABLE", "message": "会话存储暂不可用", "traceId": accepted.trace_id})
            return
    else:
        result = accepted
        yield event("meta", {"turnId": result["turnId"], "traceId": result["traceId"]})
    for offset in range(0, len(result["reply"]), 100):
        yield event("delta", {"text": result["reply"][offset:offset + 100]})
    yield event("done", result)
