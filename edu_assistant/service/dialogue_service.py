"""编排会话操作及消息受理、执行和结果入库。"""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

log = logging.getLogger("uvicorn.error")


class DialogueService:
    def __init__(self, repository, dialogue):
        self.repository, self.dialogue = repository, dialogue
        self.pending = set()

    async def create_session(self, user_id, title):
        return await run_in_threadpool(self.repository.create, user_id, title)

    async def list_sessions(self, user_id, cursor, limit):
        return await run_in_threadpool(self.repository.list, user_id, cursor, limit)

    async def state(self, user_id, session_id):
        return await run_in_threadpool(self.repository.state, user_id, session_id)

    async def history(self, user_id, session_id, cursor, limit, client_message_id):
        return await run_in_threadpool(self.repository.history, user_id, session_id, cursor, limit, client_message_id)

    async def clear_messages(self, user_id, session_id, expected_version):
        return await run_in_threadpool(self.repository.clear_messages, user_id, session_id, expected_version)

    async def delete_session(self, user_id, session_id, expected_version):
        return await run_in_threadpool(self.repository.delete_session, user_id, session_id, expected_version)

    async def accept(self, user_id, session_id, payload):
        return await run_in_threadpool(self.repository.accept, user_id, session_id, payload)

    async def process(self, user_id, accepted, payload):
        try:
            if self.dialogue.planner.model is None and payload["type"] != "confirmation" and payload.get("text") not in {"取消当前任务", "取消这个任务"}:
                result = (accepted.state, "对话模型尚未配置，请完成服务端模型配置后再试。", [])
            else:
                async with asyncio.timeout(65):
                    result = await self.dialogue.run(accepted.state, accepted.recent, payload, user_id)
        except Exception as exc:
            log.warning("chat turn incomplete trace_id=%s kind=%s", accepted.trace_id, type(exc).__name__)
            result = (accepted.state, "本轮暂未完成，请稍后再试。没有提交任何业务申请。", [])
        return await run_in_threadpool(self.repository.finish, user_id, accepted, *result)

    def start(self, user_id, accepted, payload):
        task = asyncio.create_task(self.process(user_id, accepted, payload))
        self.pending.add(task)
        task.add_done_callback(self.finished)
        return task

    def finished(self, task):
        self.pending.discard(task)
        if not task.cancelled() and (failure := task.exception()):
            log.warning("chat persistence incomplete kind=%s", type(failure).__name__)
