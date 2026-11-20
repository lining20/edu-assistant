"""定义客服 HTTP 请求的校验契约。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class NewSession(Input):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = "学习咨询"


class TurnInput(Input):
    clientMessageId: Identifier
    expectedStateVersion: int = Field(strict=True, ge=0)
    stream: bool = Field(default=False, strict=True)


class Text(TurnInput):
    type: Literal["text"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Reference(Input):
    kind: Literal["order", "cohort", "series", "order_item", "refund_request"]
    id: int = Field(strict=True, gt=0, le=2**53 - 1)


class BusinessObject(TurnInput):
    type: Literal["business_object"]
    object: Reference
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)] | None = None


class ConfirmationReference(Input):
    taskId: Identifier
    confirmationId: Identifier


class Confirmation(TurnInput):
    type: Literal["confirmation"]
    confirmation: ConfirmationReference


Message = Annotated[Text | BusinessObject | Confirmation, Field(discriminator="type")]
