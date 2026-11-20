"""现有客服三表的 ORM 映射；仅用于读写，禁止自动建表或迁移。"""

from datetime import datetime

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """现有表的声明式映射基类，不触发元数据创建。"""


class ChatSession(Base):
    """会话、业务快照、版本及数据库租约的持久化记录。"""

    __tablename__ = "chat_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    state_version: Mapped[int] = mapped_column(BigInteger)
    state_json: Mapped[dict] = mapped_column(JSON)
    next_sequence: Mapped[int] = mapped_column(BigInteger)
    processing_turn_id: Mapped[str | None] = mapped_column(String(36))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))
    last_active_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))
    expired_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))


class ChatTurn(Base):
    """消息受理、幂等摘要与可重放结果；普通文本不占用业务提交字段。"""

    __tablename__ = "chat_turn"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36))
    client_message_id: Mapped[str] = mapped_column(String(64))
    request_kind: Mapped[str] = mapped_column(String(20))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSON)
    expected_version: Mapped[int] = mapped_column(BigInteger)
    committed_version: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    response_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    trace_id: Mapped[str] = mapped_column(String(36))
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))

    task_id: Mapped[str | None] = mapped_column(String(36))
    submission_status: Mapped[str | None] = mapped_column(String(20))
    pending_scope_key: Mapped[str | None] = mapped_column(String(64))
    submission_error_code: Mapped[str | None] = mapped_column(String(64))
    submission_updated_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))
    confirmation_id: Mapped[str | None] = mapped_column(String(36))
    task_version: Mapped[int | None] = mapped_column(BigInteger)
    operation: Mapped[str | None] = mapped_column(String(64))
    submission_request_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    submission_request_hash: Mapped[str | None] = mapped_column(String(64))
    submission_result_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    reconciliation_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))
    replay_of_turn_id: Mapped[str | None] = mapped_column(String(36))


class ChatMessage(Base):
    """按服务端顺序持久化的用户问题与助手回答。"""

    __tablename__ = "chat_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36))
    turn_id: Mapped[str] = mapped_column(String(36))
    sequence_no: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(20))
    message_type: Mapped[str] = mapped_column(String(32))
    content_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3))
