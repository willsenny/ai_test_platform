"""
LLM 结构化输出 schema（Phase J Step 2）。

三类产物：
- ManualCase：手动用例（人执行的步骤 + 预期）
- UICase：UI 自动化（Playwright steps + assertions）
- ApiCase：接口自动化（request + assertions）
"""
from pydantic import BaseModel, Field


class ManualStep(BaseModel):
    action: str = Field(description="操作步骤")
    expected: str = Field(default="", description="该步骤的预期")


class ManualCase(BaseModel):
    title: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[ManualStep] = Field(default_factory=list)
    expected_result: str = Field(default="", description="整体预期结果")
    priority: str = Field(default="P1", description="P0/P1/P2")
    tags: list[str] = Field(default_factory=list)


class ManualCaseList(BaseModel):
    cases: list[ManualCase] = Field(default_factory=list)


class UIStep(BaseModel):
    action: str = Field(description="goto/fill/click/wait/select/check/hover/press")
    selector: str = Field(default="")
    value: str = Field(default="")
    description: str = Field(default="")


class UIAssertion(BaseModel):
    type: str = Field(default="text_contains", description="text_contains/text_equals/visible")
    selector: str = Field(default="")
    expected: str = Field(default="")


class UICase(BaseModel):
    title: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[UIStep] = Field(default_factory=list)
    assertions: list[UIAssertion] = Field(default_factory=list)
    priority: str = Field(default="P1")
    tags: list[str] = Field(default_factory=list)
    target_url: str = Field(default="")


class UICaseList(BaseModel):
    cases: list[UICase] = Field(default_factory=list)


class ApiAssertion(BaseModel):
    type: str = Field(default="status_equals", description="status_equals/json_field/json_contains/json_path_exists")
    path: str = Field(default="", description="JSON 路径，如 data.token")
    expected: str = Field(default="")


class ApiCase(BaseModel):
    title: str
    method: str = Field(default="GET")
    path: str = Field(default="", description="接口路径，如 /api/login")
    headers: dict = Field(default_factory=dict)
    body: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    assertions: list[ApiAssertion] = Field(default_factory=list)
    priority: str = Field(default="P1")
    tags: list[str] = Field(default_factory=list)


class ApiCaseList(BaseModel):
    cases: list[ApiCase] = Field(default_factory=list)


SCHEMA_BY_KIND = {
    "manual": ManualCaseList,
    "ui": UICaseList,
    "api": ApiCaseList,
}
