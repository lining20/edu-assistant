"""装配中台动作、共享目录、规划器和对话引擎。"""

from langchain_openai import ChatOpenAI

from edu_assistant.conf.config import ROOT
from edu_assistant.engine.dialogue_engine import DialogueEngine
from edu_assistant.plan.turn_plan_validator import TurnPlanValidator
from edu_assistant.plan.turn_planner import TurnPlanner
from edu_assistant.task.action.edu_data import EduData
from edu_assistant.task.flow.loader import FlowCatalog


def build_dialogue(settings, client):
    """
    装配对话引擎以及模型、查询动作和业务门禁。

    :param settings: 当前服务配置，包含模型和订单明细服务地址。
    :param client: 生命周期管理的异步 HTTP 客户端。
    :return: 配置完成的对话引擎。
    """
    data = EduData(client, settings.order_items_base_url)
    actions = {"query_courses": data.query_courses, "query_order": data.query_order,
               "query_learning_progress": data.query_learning_progress}
    checks = {"order_status": data.order_status}
    catalog = FlowCatalog(ROOT, actions, settings.knowledge_version, checks=checks)
    model = (ChatOpenAI(model=settings.model_name, api_key=settings.model_api_key,
                        base_url=settings.model_base_url or None, temperature=0, timeout=25, max_retries=0)
             if settings.model_api_key and settings.model_name else None)
    return DialogueEngine(catalog, TurnPlanner(ROOT, model, catalog), TurnPlanValidator(ROOT, catalog), actions, checks=checks)
