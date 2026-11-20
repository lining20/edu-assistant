"""渲染提示词并请求模型生成单轮计划。"""

import json

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage

from edu_assistant.task.flow.loader import KNOWLEDGE_TOPICS


class TurnPlanner:
    def __init__(self, root, model, catalog):
        folder = root / "configs" / "prompts"
        self.template = Environment(loader=FileSystemLoader(folder), undefined=StrictUndefined).get_template("turn_plan.jinja2")
        self.model, self.catalog = model, catalog

    async def plan(self, state, recent, message):
        prompt = self.template.render(flows=self.catalog.description(), context=state, recent_turns=recent,
                                      knowledge_intents={**KNOWLEDGE_TOPICS, **{
                                          key: value["title"] for key, value in self.catalog.knowledge.items()}})
        result = await self.model.ainvoke([SystemMessage(content=prompt),
                                          HumanMessage(content=json.dumps(message, ensure_ascii=False))])
        content = result.content if isinstance(result.content, str) else result.text
        content = content.strip()
        if content.startswith("```") and content.endswith("```"):
            content = content.split("\n", 1)[-1][:-3]
        return json.loads(content)
