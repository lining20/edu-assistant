"""校验本地演示身份并注入对话服务。"""

from typing import Annotated

from fastapi import Depends, Header, Request

from edu_assistant.domain.errors import ChatError
from edu_assistant.service.dialogue_service import DialogueService


async def identity(request: Request, user_header: Annotated[str | None, Header(alias="X-User-Id")] = None):
    if not request.app.state.settings.chat_demo_auth_enabled:
        raise ChatError(401, "DEMO_AUTH_DISABLED", "本地演示身份未启用")
    if not user_header or not user_header.isascii() or not user_header.isdecimal() or len(user_header) > 19:
        raise ChatError(401, "INVALID_USER_ID", "请连接有效的学员账号")
    user_id = int(user_header)
    if not 0 < user_id <= 2**63 - 1:
        raise ChatError(401, "INVALID_USER_ID", "请连接有效的学员账号")
    return user_id


User = Annotated[int, Depends(identity)]

def dialogue_service(request: Request) -> DialogueService:
    return request.app.state.service


ServiceDependency = Annotated[DialogueService, Depends(dialogue_service)]
