"""客服服务的可展示错误。"""


class ChatError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code
