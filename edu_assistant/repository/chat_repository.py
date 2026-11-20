"""会话、轮次、消息三表的事务边界。"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from edu_assistant.domain.errors import ChatError
from edu_assistant.domain.turn import Accepted
from edu_assistant.repository.orm.chat_models import ChatMessage, ChatSession, ChatTurn


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def stamp(value):
    return value.replace(tzinfo=UTC).isoformat()


def uid():
    return str(uuid4())


def empty_state():
    return {"activeTask": None, "suspendedTasks": []}


def compatible(record):
    return {"activeTask", "suspendedTasks"} <= record.state_json.keys()


def page(rows, limit, render, cursor):
    more = len(rows) > limit
    return {"items": [render(row) for row in rows[:limit]],
            "hasMore": more, "nextCursor": cursor(rows[limit - 1]) if more else None}


class Repository:
    def __init__(self, engine):
        self.sessions = sessionmaker(engine)

    def owned(self, db, session_id, user_id, *, lock=False):
        query = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        record = db.scalar(query.with_for_update() if lock else query)
        if record is None:
            raise ChatError(404, "SESSION_NOT_FOUND", "会话不存在")
        return record

    @staticmethod
    def present(record, current):
        expired = (not compatible(record) or record.status != "active"
                   or current >= record.last_active_at + timedelta(hours=1))
        return {"sessionId": record.id, "title": record.title, "stateVersion": record.state_version,
                "createdAt": stamp(record.created_at), "status": "expired" if expired else "active"}

    def create(self, user_id, title):
        with self.sessions.begin() as db:
            current = now()
            record = ChatSession(id=uid(), user_id=user_id, title=title, status="active", state_version=0,
                                 state_json=empty_state(), next_sequence=1, last_active_at=current,
                                 created_at=current, updated_at=current)
            db.add(record)
            return self.present(record, current)

    def list(self, user_id, cursor, limit):
        with self.sessions() as db:
            query = select(ChatSession).where(ChatSession.user_id == user_id)
            if cursor:
                prior = self.owned(db, cursor, user_id)
                query = query.where((ChatSession.created_at < prior.created_at) |
                                    ((ChatSession.created_at == prior.created_at) & (ChatSession.id < prior.id)))
            records = db.scalars(query.order_by(ChatSession.created_at.desc(), ChatSession.id.desc()).limit(limit + 1)).all()
            current = now()
            return page(records, limit, lambda record: self.present(record, current), lambda record: record.id)

    def state(self, user_id, session_id):
        with self.sessions() as db:
            record = self.owned(db, session_id, user_id)
            current = now()
            result = self.present(record, current)
            active = result["status"] == "active"
            return {**result, **(record.state_json if active else empty_state()), "pendingSubmissions": [],
                    "processing": bool(active and record.lease_until and record.lease_until > current)}

    def history(self, user_id, session_id, cursor, limit, client_message_id):
        with self.sessions() as db:
            self.owned(db, session_id, user_id)
            query = (select(ChatMessage, ChatTurn).join(ChatTurn, ChatTurn.id == ChatMessage.turn_id)
                     .where(ChatMessage.session_id == session_id, ChatMessage.sequence_no > cursor))
            if client_message_id:
                query = query.where(ChatTurn.client_message_id == client_message_id)
            rows = db.execute(query.order_by(ChatMessage.sequence_no).limit(limit + 1)).all()
            return page(rows, limit, self.message, lambda row: str(row[0].sequence_no))

    def clear_messages(self, user_id, session_id, expected_version):
        return self.remove_session_data(user_id, session_id, expected_version, delete_session=False)

    def delete_session(self, user_id, session_id, expected_version):
        return self.remove_session_data(user_id, session_id, expected_version, delete_session=True)

    def remove_session_data(self, user_id, session_id, expected_version, *, delete_session):
        with self.sessions.begin() as db:
            record = self.owned(db, session_id, user_id, lock=True)
            current = now()
            legacy = not compatible(record)
            if legacy and not delete_session:
                raise ChatError(409, "LEGACY_SESSION_READ_ONLY", "旧版会话不能清空后继续使用，可直接删除会话")
            if record.lease_until and record.lease_until > current:
                raise ChatError(409, "SESSION_BUSY", "当前会话仍在处理，请稍后再试")
            if record.state_version != expected_version:
                raise ChatError(409, "STATE_VERSION_CONFLICT", "会话已变化，请恢复会话后重新确认")
            turns = ChatTurn.session_id == session_id
            if legacy:
                unsettled = db.scalar(select(ChatTurn.id).where(
                    turns,
                    ChatTurn.submission_status.is_not(None),
                    ChatTurn.submission_status.not_in(("succeeded", "failed"))
                    | ((ChatTurn.status != "completed") & ChatTurn.submission_result_json.is_not(None)),
                ).limit(1).with_for_update())
                if unsettled is not None:
                    raise ChatError(409, "BUSINESS_SUBMISSION_PENDING", "此会话仍有待核对的业务提交，暂不能删除")
                db.execute(update(ChatTurn).where(turns, ChatTurn.replay_of_turn_id.is_not(None))
                           .values(replay_of_turn_id=None))
            record.processing_turn_id = record.lease_token = record.lease_until = None
            db.flush()
            db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
            db.execute(delete(ChatTurn).where(turns))
            if delete_session:
                db.delete(record)
                return {"sessionId": session_id}
            record.state_json, record.updated_at = empty_state(), current
            record.state_version += 1
            return {**self.present(record, current), **record.state_json, "pendingSubmissions": [], "processing": False}

    @staticmethod
    def message(row):
        message, turn = row
        return {**message.content_json, "messageId": message.id, "turnId": turn.id,
                "sequence": message.sequence_no, "role": message.role, "type": message.message_type,
                "clientMessageId": turn.client_message_id if message.role == "user" else None,
                "processingStatus": turn.status, "createdAt": stamp(message.created_at)}

    def accept(self, user_id, session_id, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.sessions.begin() as db:
            record = self.owned(db, session_id, user_id, lock=True)
            if not compatible(record):
                raise ChatError(410, "SESSION_EXPIRED", "旧版会话只供查看，请开启新会话")
            prior = db.scalar(select(ChatTurn).where(ChatTurn.session_id == session_id,
                              ChatTurn.client_message_id == payload["clientMessageId"]))
            current = now()
            if prior and prior.request_hash != digest:
                raise ChatError(409, "IDEMPOTENCY_CONFLICT", "同一消息 ID 不可更换请求内容")
            if prior and prior.status == "completed":
                return prior.response_json
            if record.lease_until and record.lease_until > current:
                raise ChatError(409, "TURN_IN_PROGRESS" if prior else "SESSION_BUSY", "上一轮仍在处理")
            if self.present(record, current)["status"] == "expired":
                if record.status == "active":
                    record.status, record.expired_at, record.updated_at = "expired", current, current
                    record.state_json = empty_state()
                    db.commit()
                raise ChatError(410, "SESSION_EXPIRED", "会话已过期，请开启新会话")
            if record.state_version != payload["expectedStateVersion"]:
                raise ChatError(409, "STATE_VERSION_CONFLICT", "会话状态已变化，请恢复会话")
            if record.processing_turn_id and (prior is None or prior.id != record.processing_turn_id):
                abandoned = db.get(ChatTurn, record.processing_turn_id)
                if abandoned and abandoned.status == "processing":
                    abandoned.status, abandoned.error_code, abandoned.finished_at = "failed", "LEASE_EXPIRED", current
            if prior and prior.status != "processing":
                raise ChatError(409, "TURN_FAILED", "原轮次已结束，请恢复会话后发送新消息")
            token = uid()
            recent = db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
                                .order_by(ChatMessage.sequence_no.desc()).limit(8)).all()
            context = [{"role": row.role, "text": row.content_json["text"]}
                       for row in reversed(recent) if row.message_type == "text" and (not prior or row.turn_id != prior.id)]
            if not prior:
                prior = ChatTurn(id=uid(), session_id=session_id, client_message_id=payload["clientMessageId"],
                                 request_kind=payload["type"], request_hash=digest, request_json=payload,
                                 expected_version=record.state_version, status="processing", trace_id=uid(), started_at=current)
                db.add(prior)
                db.flush()
                self.append(db, record, prior, "user", payload["type"],
                            {key: payload[key] for key in ("text", "object", "confirmation") if key in payload}, current)
                record.last_active_at = current
            record.processing_turn_id, record.lease_token = prior.id, token
            record.lease_until, record.updated_at = current + timedelta(seconds=90), current
            return Accepted(record.id, prior.id, token, prior.trace_id, record.state_json, context)

    @staticmethod
    def append(db, record, turn, role, kind, content, current):
        message_id = uid()
        db.add(ChatMessage(id=message_id, session_id=record.id, turn_id=turn.id, sequence_no=record.next_sequence,
                           role=role, message_type=kind, content_json=content, created_at=current))
        record.next_sequence += 1
        return message_id

    def finish(self, user_id, accepted, state, reply, cards):
        with self.sessions.begin() as db:
            record = self.owned(db, accepted.session_id, user_id, lock=True)
            turn = db.get(ChatTurn, accepted.turn_id)
            current = now()
            if (turn is None or record.lease_token != accepted.token or record.lease_until <= current
                    or record.state_version != turn.expected_version or turn.status != "processing"):
                raise ChatError(409, "LEASE_EXPIRED", "本轮处理超时，请恢复会话")
            message_id = self.append(db, record, turn, "assistant", "text", {"text": reply, "cards": cards}, current)
            record.state_version += 1
            record.state_json, record.updated_at = state, current
            record.processing_turn_id = record.lease_token = record.lease_until = None
            result = {"sessionId": record.id, "turnId": turn.id, "messageId": message_id, "traceId": turn.trace_id,
                      "stateVersion": record.state_version, "reply": reply, "cards": cards, **state, "processing": False}
            turn.committed_version, turn.response_json = record.state_version, result
            turn.status, turn.finished_at = "completed", current
            return result
