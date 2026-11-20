"""教育中台只读业务动作。"""

import httpx

from edu_assistant.domain.cards import card
from edu_assistant.domain.errors import ChatError


class EduData:
    """通过 HTTP 读取中台及订单明细服务的本人业务数据。"""

    def __init__(self, client, order_items_base_url):
        """
        注入只读业务查询所需的客户端和地址。

        :param client: 以中台服务为默认地址的异步 HTTP 客户端。
        :param order_items_base_url: 订单明细服务的 HTTP 根地址。
        :return: None。
        """
        self.client = client
        self.order_items_base_url = order_items_base_url.rstrip("/")

    async def get(self, path, user_id, *, service_url=None, **params):
        """
        执行有身份约束的业务查询并校验响应外层结构。

        :param path: 受控业务接口路径。
        :param user_id: 当前用户 ID，公开查询可为 None。
        :param service_url: 指定只读服务的根地址，默认使用中台 API。
        :param params: 传入业务接口的查询参数。
        :return: 成功响应中的业务数据。
        """
        try:
            headers = {"X-User-Id": str(user_id)} if user_id is not None else {}
            response = await self.client.get((service_url or "/api/v1") + path, headers=headers, params=params)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChatError(502, "DATA_UNAVAILABLE", "暂时无法连接业务服务") from exc
        if response.status_code in (401, 403, 404):
            raise ChatError(response.status_code, "DATA_NOT_ACCESSIBLE", "业务记录不存在或当前账号无权访问")
        if not response.is_success or not isinstance(payload, dict) or payload.get("code") != 0 or "data" not in payload:
            raise ChatError(502, "DATA_UNAVAILABLE", "业务服务未返回有效结果")
        return payload["data"]

    async def pages(self, path, user_id, **params):
        page_no = 1
        while True:
            data = await self.get(path, user_id, pageNo=page_no, pageSize=100, **params)
            from_rows = data["list"]
            yield from_rows
            if not from_rows or page_no * data["pageSize"] >= data["total"]:
                return
            page_no += 1

    async def order(self, slots, user_id):
        order_id = slots.get("order_id")
        if order_id is None:
            async for rows in self.pages("/orders", user_id):
                match = next((row for row in rows if row["orderNo"].casefold() == slots["order_number"].casefold()), None)
                if match:
                    order_id = match["orderId"]
                    break
        if order_id is None:
            raise ChatError(404, "ORDER_NOT_FOUND", "未找到本人名下的该订单，请核对订单号。")
        return await self.get(f"/orders/{order_id}", user_id)

    async def query_order(self, slots, user_id):
        order = await self.order(slots, user_id)
        return f"已查到订单 {order['orderNo']}。中台暂未提供报名明细。", [card("order_detail", **order)]

    async def order_status(self, slots, user_id) -> tuple[str, dict[str, int]]:
        """
        查询本人订单的状态和业务页可使用的标准订单 ID。

        :param slots: 包含订单号或订单 ID 的任务槽位。
        :param user_id: 当前认证用户的 ID，用于中台订单归属校验。
        :return: 中台订单状态及受控导航参数。
        """
        order = await self.order(slots, user_id)
        if not isinstance(order, dict):
            raise ChatError(502, "DATA_UNAVAILABLE", "暂时无法核验订单状态，请稍后再试。")
        status, order_id = order.get("orderStatusCode"), order.get("orderId")
        if not isinstance(status, str) or not status or type(order_id) is not int or not 0 < order_id < 2**53:
            raise ChatError(502, "DATA_UNAVAILABLE", "暂时无法核验订单状态，请稍后再试。")
        if status != "cancelled":
            refund = await self.get(f"/orders/{order_id}/refund-status", user_id, service_url=self.order_items_base_url)
            if not isinstance(refund, dict) or not isinstance(refund.get("inProgress"), bool):
                raise ChatError(502, "DATA_UNAVAILABLE", "暂时无法核验订单的退款状态，请稍后再试。")
            if refund["inProgress"]:
                raise ChatError(409, "REFUND_IN_PROGRESS", "这笔订单已有退款申请正在处理，暂不能重复申请。可在「服务与售后」查看进度，或选择其他订单。")
        return status, {"orderId": order_id}

    async def query_courses(self, slots, user_id):
        series_id = slots.get("series_id")
        if series_id is None:
            results = (await self.get("/series", None, keyword=slots["course_keyword"], pageSize=5))["list"]
            if not results:
                raise ChatError(404, "COURSE_NOT_FOUND", "没有找到匹配课程，请换一个关键词。")
            exact = next((row for row in results if row["seriesName"].casefold() == slots["course_keyword"].casefold()), None)
            if not exact and len(results) > 1:
                return "找到多门相关课程。可提供完整课程名称继续查询。", [card("course_list", courses=results)]
            series_id = (exact or results[0])["seriesId"]
        course = await self.get(f"/series/{series_id}", None)
        cohorts = await self.get(f"/series/{series_id}/cohorts", None)
        return f"已查到「{course['seriesName']}」。班次报名状态请以业务页面为准。", [card("course_list", course=course, cohorts=cohorts)]

    async def query_learning_progress(self, slots, user_id):
        cohort_id = slots.get("cohort_id")
        if cohort_id is None:
            matches = []
            async for rows in self.pages("/me/cohorts", user_id):
                matches.extend(row for row in rows if slots["cohort_name"].casefold() in row["cohortName"].casefold())
            exact = [row for row in matches if row["cohortName"].casefold() == slots["cohort_name"].casefold()]
            matches = exact or matches
            if len(matches) != 1:
                detail = "、".join(row["cohortName"] for row in matches[:5])
                message = f"匹配到多个班次（{detail}），请提供完整班次名称或发送班次卡片。" if matches else "未找到本人班次，请核对班次名称。"
                raise ChatError(404, "COHORT_NOT_UNIQUE", message)
            cohort_id = matches[0]["cohortId"]
        progress = await self.get(f"/me/cohorts/{cohort_id}/progress", user_id)
        exams = (await self.get("/me/exams", user_id, cohortId=cohort_id, pageSize=10))["list"]
        return "这是该班次的现有学习记录和最多 10 条考试记录，不代表全部应学内容。", [card("learning_progress", progress=progress, exams=exams)]
