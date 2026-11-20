"""加载并校验版本化流程及知识目录。"""

import yaml

HANDOFFS = {
    "refund_service": "前往退款申请",
    "refund_application_page": "前往退款",
    "ticket_service": "前往服务工单",
}
KNOWLEDGE_TOPICS = {"policy": "政策、规则、联系方式及操作指南"}


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def collect_fields(step):
    return step.get("any_of") or [step["slot"]]


def compile_guards(steps, checks, path):
    seen = {}
    compiled = []
    for index, step in enumerate(steps):
        if step["type"] == "guard":
            retry = seen.get(step.get("retry"))
            condition = step.get("reject_when")
            if (retry is None or steps[retry]["type"] != "collect" or step.get("check") not in checks
                    or not isinstance(condition, dict) or not isinstance(condition.get("equals"), str)
                    or not condition["equals"] or not isinstance(step.get("prompt"), str) or not step["prompt"].strip()):
                raise ValueError(f"{path}: 无效条件检查 {step['id']}")
            step = {**step, "retry_fields": collect_fields(steps[retry]),
                    "reset_fields": tuple(dict.fromkeys(
                        field for source in steps[retry:] if source["type"] == "collect"
                        for field in collect_fields(source)
                    ))}
        seen[step["id"]] = index
        compiled.append(step)
    return compiled


class FlowCatalog:
    def __init__(self, root, actions, knowledge_version, *, checks=()):
        config = root / "configs"
        self.slots = read_yaml(config / "slots.yaml")
        self.flows = {}
        self.current = {}
        for path in sorted((config / "flows").glob("*.yaml")):
            flow = read_yaml(path)
            steps = {step["id"]: step for step in flow["steps"]}
            identity = flow["id"], flow["version"]
            if (len(steps) != len(flow["steps"]) or identity in self.flows
                    or not flow["steps"] or flow["steps"][0]["type"] != "entry"):
                raise ValueError(f"{path}: 流程版本、步骤 ID 或入口无效")
            visited = set()
            ordered = []
            step = flow["steps"][0]
            while True:
                kind = step["type"]
                if step["id"] in visited:
                    raise ValueError(f"{path}: 步骤跳转包含循环")
                visited.add(step["id"])
                ordered.append(step)
                if kind == "end":
                    break
                condition = step.get("when")
                if (kind not in {"entry", "collect", "action", "guard", "handoff"} or step.get("next") not in steps
                        or kind == "collect" and not set(collect_fields(step)) <= self.slots.keys()
                        or kind == "action" and step.get("action") not in actions
                        or kind == "handoff" and step.get("target") not in HANDOFFS
                        or condition and condition["slot"] not in self.slots):
                    raise ValueError(f"{path}: 无效步骤 {step['id']}")
                if kind == "handoff" and step["target"] == "refund_application_page" and not any(
                    source["type"] == "guard" and source.get("check") == "order_status"
                    and not source.get("when") for source in ordered
                ):
                    raise ValueError(f"{path}: 退款入口需要在跳转前核验本人订单状态")
                step = steps[step["next"]]
            if len(visited) != len(steps):
                raise ValueError(f"{path}: 存在不可达步骤")
            self.flows[identity] = {**flow, "steps": compile_guards(ordered, checks, path)}
            if flow["version"] > self.current.get(flow["id"], 0):
                self.current[flow["id"]] = flow["version"]
        self.knowledge_version = knowledge_version
        if not knowledge_version.startswith("v") or not knowledge_version[1:].isdecimal():
            raise ValueError("知识版本须为 v 加数字")
        catalog = read_yaml(root / "knowledge" / "releases" / knowledge_version / "catalog.yaml")
        if catalog["version"] != knowledge_version or not isinstance(catalog["entries"], list):
            raise ValueError("知识目录版本或记录格式无效")
        self.knowledge = {}
        for entry in catalog["entries"]:
            if (not all(isinstance(entry.get(key), str) and entry[key].strip()
                        for key in ("id", "title", "answer"))
                    or entry["id"] in self.knowledge or entry["id"] in KNOWLEDGE_TOPICS):
                raise ValueError("知识条目缺少有效内容或 ID 重复")
            self.knowledge[entry["id"]] = entry

    def description(self):
        return [{"id": flow_id, "description": flow["description"],
                 "slots": {field: self.slots[field] for step in flow["steps"] if step["type"] == "collect"
                           for field in collect_fields(step)}}
                for flow_id, version in self.current.items()
                for flow in (self.flows[flow_id, version],)]
