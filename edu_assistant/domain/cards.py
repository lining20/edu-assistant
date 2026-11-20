"""业务卡片的统一输出格式。"""


def card(kind, **data):
    return {"type": kind, "data": data}
