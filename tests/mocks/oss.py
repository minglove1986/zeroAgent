"""OSS Mock 占位。

@author 赵振明
@date 2026-07-21 15:31:36
"""


class MockOSS:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def presign(self, key: str) -> str:
        return f"https://mock-oss.local/{key}"
