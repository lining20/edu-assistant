"""执行校验后的计划，推进和恢复任务。"""

import asyncio
from copy import deepcopy
from uuid import uuid4

from jsonschema import ValidationError

from edu_assistant.domain.cards import card
from edu_assistant.domain.errors import ChatError
from edu_assistant.task.flow.loader import HANDOFFS, collect_fields


class DialogueEngine:
    def __init__(self, catalog, planner, validator, actions, *, checks):
        self.catalog, self.planner, self.validator, self.actions = catalog, planner, validator, actions
        self.checks = checks

    def card_for_handoff(self, target, slots):
        summary = {self.catalog.slots[key]["label"]: self.catalog.slots[key].get("values", {}).get(value, value)
                   for key, value in slots.items()}
        return card("service_entry", title=HANDOFFS[target], summary=summary, action={"target": target})

    async def run(self, state, recent, message, user_id):
        state = deepcopy(state)
        active, stack = state["activeTask"], state["suspendedTasks"]
        if message["type"] == "confirmation":
            return state, "客服不会提交售后业务，请通过业务页面办理。", []
        object_slots = self.validator.object_slots(active, message)
        if message.get("text") in {"取消当前任务", "取消这个任务"}:
            if not active:
                return state, "当前没有可取消的任务。", []
            plan = {"task": {"commands": [{"command": "cancel_task", "task_id": active["taskId"]}]},
                    "knowledge": None, "chitchat": None}
        elif object_slots:
            plan = {"task": {"commands": [{"command": "set_slots", "slots": object_slots}]},
                    "knowledge": None, "chitchat": None}
        else:
            try:
                raw = await self.planner.plan(state, recent, message)
                plan = self.validator.validate(raw, state, message)
            except (ValidationError, ValueError, KeyError):
                return state, "我还不能确定你的意思，请说明要办理的业务或补充当前所需信息。", []
        if plan["knowledge"]:
            entries = [self.catalog.knowledge[key] for key in plan["knowledge"]["intents"] if key in self.catalog.knowledge]
            if not entries:
                return state, "当前没有查到已审核的相关资料，请以平台公布的信息为准。", []
            return state, "\n".join(entry["answer"] for entry in entries), [
                card("knowledge_sources", version=self.catalog.knowledge_version, titles=[entry["title"] for entry in entries])]
        if plan["chitchat"] is not None:
            return state, "你好，我可以帮你查询课程、订单或学习进度，也能引导你办理退款和工单。", []
        if not plan["task"]:
            return state, "请告诉我你想查询课程、订单、学习进度，还是需要售后帮助？", []
        notes = []
        for command in plan["task"]["commands"]:
            kind = command["command"]
            if kind == "start_flow":
                flow_id = command["flow"]
                if active and active["type"] == flow_id:
                    continue
                if active:
                    active["status"] = "suspended"
                    stack.append(active)
                active = {"taskId": str(uuid4()), "type": flow_id, "flowVersion": self.catalog.current[flow_id],
                          "status": "collecting", "slots": {}, "missingSlots": []}
            elif kind == "set_slots":
                new_slots = command["slots"]
                flow = self.catalog.flows[active["type"], active["flowVersion"]]
                for step in flow["steps"]:
                    alternatives = step.get("any_of", [])
                    fresh = next((key for key in reversed(alternatives) if key in new_slots), None)
                    if fresh:
                        for sibling in set(alternatives) - {fresh}:
                            active["slots"].pop(sibling, None)
                            new_slots.pop(sibling, None)
                active["slots"].update(new_slots)
                if new_slots.get("ticket_type") not in (None, "refund"):
                    active["slots"].pop("refund_request_id", None)
            elif kind == "cancel_task":
                active = stack.pop() if stack else None
                notes.append("已取消当前对话任务，不会撤销任何已办理的业务。")
            elif kind == "resume_task":
                resumed = next(task for task in stack if task["taskId"] == command["task_id"])
                stack.remove(resumed)
                if active:
                    active["status"] = "suspended"
                    stack.append(active)
                active = resumed
                notes.append("已恢复暂存任务。")
        cards = []
        while active:
            active["status"] = "collecting"
            state["activeTask"] = active
            done, reply, next_cards = await self.advance(active, user_id)
            notes.append(reply)
            cards.extend(next_cards)
            if not done:
                break
            active = stack.pop() if stack else None
            if active:
                notes.append("继续之前暂存的任务：")
        state["activeTask"] = active
        return state, "\n".join(notes), cards

    async def advance(self, task, user_id):
        """
        推进配置流程，返回下一步提示、只读查询结果或业务办理入口。

        :param task: 本轮正在推进的任务及其固定流程版本。
        :param user_id: 当前认证用户的 ID，用于只读业务检查。
        :return: 任务是否结束、回复文本和本轮卡片列表。
        """
        flow = self.catalog.flows[task["type"], task["flowVersion"]]
        slots = task["slots"]
        verified_references = {}
        for step in flow["steps"]:
            kind = step["type"]
            condition = step.get("when")
            if condition and slots.get(condition["slot"]) != condition["equals"]:
                continue
            if kind == "collect":
                fields = collect_fields(step)
                if not any(field in slots for field in fields):
                    task["missingSlots"] = fields
                    return False, step["prompt"], []
            if kind == "guard":
                try:
                    async with asyncio.timeout(14):
                        observed, references = await self.checks[step["check"]](slots, user_id)
                except ChatError as exc:
                    if exc.status in (403, 404) or exc.code == "REFUND_IN_PROGRESS":
                        self.retry_guard(task, step)
                    return False, str(exc), []
                except TimeoutError:
                    return False, "业务状态核验超时，请稍后再试。", []
                if observed == step["reject_when"]["equals"]:
                    self.retry_guard(task, step)
                    return False, step["prompt"], []
                verified_references.update(references)
            if kind == "action":
                try:
                    async with asyncio.timeout(14):
                        reply, cards = await self.actions[step["action"]](slots, user_id)
                    return True, reply, cards
                except ChatError as exc:
                    if exc.status == 404:
                        for field in collect_fields(flow["steps"][1]):
                            slots.pop(field, None)
                        task["missingSlots"] = collect_fields(flow["steps"][1])
                    return False, str(exc), []
                except TimeoutError:
                    return False, "业务查询超时，请稍后再试。", []
            if kind == "handoff":
                if step["target"] == "refund_application_page":
                    # 从本轮通过的订单核验取业务 ID，避免将聊天里的候选值作为跳转参数。
                    order_id = verified_references["orderId"]
                    return True, "已核对订单，请点击「前往退款」填写申请信息。", [card(
                        "service_entry", title="申请退款", action={
                            "target": step["target"], "label": HANDOFFS[step["target"]],
                            "params": {"orderId": order_id},
                        },
                    )]
                return True, "信息已收集。点击卡片前往对应业务页面办理；客服没有提交申请。", [
                    self.card_for_handoff(step["target"], slots)]
        return True, "对话任务已结束。", []

    @staticmethod
    def retry_guard(task, step):
        for field in step["reset_fields"]:
            task["slots"].pop(field, None)
        task["missingSlots"] = step["retry_fields"]
