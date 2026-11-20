"""已受理轮次在仓储、服务和传输间传递的上下文。"""

from dataclasses import dataclass


@dataclass
class Accepted:
    session_id: str
    turn_id: str
    token: str
    trace_id: str
    state: dict
    recent: list
