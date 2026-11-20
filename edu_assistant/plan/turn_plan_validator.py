"""校验模型计划结构、命令目标和候选槽位来源。"""

import json
import re
from decimal import Decimal, InvalidOperation

from jsonschema import Draft202012Validator

from edu_assistant.task.flow.loader import KNOWLEDGE_TOPICS, collect_fields


class TurnPlanValidator:
    def __init__(self, root, catalog):
        self.schema = Draft202012Validator(json.loads((root / "configs/prompts/turn_plan.schema.json").read_text(encoding="utf-8")))
        self.catalog = catalog

    def object_slots(self, task, message):
        if not task or message["type"] != "business_object" or message.get("text"):
            return {}
        reference = message["object"]
        return {
            field: reference["id"]
            for field in task["missingSlots"]
            if self.catalog.slots[field].get("object_type") == reference["kind"]
        }

    def validate(self, plan, state, message):
        self.schema.validate(plan)
        if not plan["task"]:
            if plan["knowledge"] and not set(plan["knowledge"]["intents"]) <= (self.catalog.knowledge.keys() | KNOWLEDGE_TOPICS.keys()):
                raise ValueError("未知知识意图")
            return plan
        commands = plan["task"]["commands"]
        kinds = tuple(command["command"] for command in commands)
        if kinds not in {("start_flow",), ("start_flow", "set_slots"), ("set_slots",), ("cancel_task",), ("resume_task",)}:
            raise ValueError("无效命令序列")
        active = state["activeTask"]
        first = commands[0]
        if kinds == ("cancel_task",):
            if not active or active["taskId"] != first["task_id"]:
                raise ValueError("无效取消目标")
        if kinds == ("resume_task",):
            if first["task_id"] not in {task["taskId"] for task in state["suspendedTasks"]}:
                raise ValueError("无效恢复目标")
        if first["command"] == "start_flow":
            version = self.catalog.current.get(first["flow"])
            if version is None:
                raise ValueError("无效流程")
            flow = self.catalog.flows[first["flow"], version]
        elif active and kinds == ("set_slots",):
            flow = self.catalog.flows[active["type"], active["flowVersion"]]
        elif kinds == ("set_slots",):
            raise ValueError("没有补槽目标")
        if kinds[-1] == "set_slots":
            allowed = {field for step in flow["steps"] if step["type"] == "collect" for field in collect_fields(step)}
            supplied = commands[-1]["slots"]
            supplied = {key: self.value(key, value, message) for key, value in supplied.items() if key in allowed}
            commands[-1]["slots"] = {key: val for key, val in supplied.items() if val is not None}
        return plan

    def value(self, field, value, message):
        spec = self.catalog.slots[field]
        text = message.get("text", "").casefold()
        reference = message.get("object") or {}
        rendered = str(value).strip()
        if spec.get("source") == "action" or not rendered or len(rendered) > 2000:
            return None
        if spec["type"] == "identifier":
            if reference.get("kind") == spec.get("object_type") and str(reference["id"]) == rendered:
                return reference["id"]
            if field == "refund_request_id" and rendered.isascii() and rendered.isdecimal() and rendered in text:
                return int(rendered) if 0 < int(rendered) <= 2**53 - 1 else None
            return None
        if spec["type"] == "enum":
            label = spec["values"].get(rendered)
            return rendered if label and (label.casefold() in text or rendered.casefold() in text) else None
        if spec["type"] == "decimal":
            try:
                amount = Decimal(rendered)
                return format(amount, ".2f") if (amount.is_finite() and 0 < amount < 10**12 and amount.as_tuple().exponent >= -2
                    and any(amount == Decimal(number) for number in amount_candidates(text))) else None
            except InvalidOperation:
                return None
        return rendered if rendered.casefold() in text else None


def amount_candidates(text):
    return re.findall(r"(?<![\d.\-])\d{1,12}(?:\.\d{1,2})?(?![\d.])", text)
