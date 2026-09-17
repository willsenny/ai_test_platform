"""
OpenAPI / Swagger 解析器（Phase J Step 3）。

输入公开可访问的 spec（OpenAPI 3 / Swagger 2），输出接口测试场景：
- 每个 endpoint 生成 正常 / 缺参异常 / 边界 场景
- 断言：status_equals + json_schema + json_field（来自响应 schema/example）
- 请求体从 schema 生成示例

同时提供 `fetch_spec(url)` 供服务层拉取。
"""
import copy

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_SUCCESS_CODES = ("200", "201", "202", "203", "204")


# ============================================================
# 拉取
# ============================================================
def fetch_spec(url: str, timeout: float = 15.0) -> dict:
    """拉取公开 OpenAPI/Swagger spec（JSON，失败尝试 YAML）。"""
    import httpx

    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        try:
            import yaml  # type: ignore

            return yaml.safe_load(resp.text)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"spec is neither JSON nor YAML: {exc}") from exc


def is_openapi(spec: dict) -> bool:
    return isinstance(spec, dict) and ("openapi" in spec or spec.get("swagger") == "2.0")


def base_url_from_spec(spec: dict) -> str:
    if spec.get("servers"):
        return str(spec["servers"][0].get("url", "")).rstrip("/")
    scheme = (spec.get("schemes") or ["https"])[0]
    host = spec.get("host", "")
    base_path = spec.get("basePath", "")
    return f"{scheme}://{host}{base_path}".rstrip("/") if host else base_path.rstrip("/")


# ============================================================
# $ref 解析
# ============================================================
def resolve_refs(spec: dict, node, _depth: int = 0):
    if _depth > 20 or not isinstance(node, (dict, list)):
        return node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target = spec
            for token in ref[2:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                target = (target or {}).get(token) if isinstance(target, dict) else None
            return resolve_refs(spec, target, _depth + 1)
        return {k: resolve_refs(spec, v, _depth + 1) for k, v in node.items()}
    return [resolve_refs(spec, item, _depth + 1) for item in node]


# ============================================================
# endpoints
# ============================================================
def parse_endpoints(spec: dict) -> list[dict]:
    """spec → endpoint 列表。"""
    spec = resolve_refs(spec, spec)
    endpoints: list[dict] = []
    for path, operations in (spec.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            endpoints.append(_build_endpoint(path, method.lower(), operation, spec))
    return endpoints


def _build_endpoint(path: str, method: str, op: dict, spec: dict) -> dict:
    body_schema = {}
    body_required = []
    content = op.get("requestBody", {}).get("content", {}) if isinstance(op.get("requestBody"), dict) else {}
    json_content = content.get("application/json") or next(iter(content.values()), {}) if content else {}
    if isinstance(json_content, dict):
        body_schema = json_content.get("schema") or {}
        body_required = list(body_schema.get("required") or []) if isinstance(body_schema, dict) else []

    # Swagger 2: body 参数
    parameters = []
    for param in op.get("parameters", []) or []:
        if not isinstance(param, dict):
            continue
        if param.get("in") == "body":
            body_schema = param.get("schema") or {}
            body_required = list(body_schema.get("required") or [])
        else:
            parameters.append(param)

    responses = op.get("responses") or {}
    success_code, success_schema = _pick_success(responses)
    error_code = _pick_error(responses)

    return {
        "method": method.upper(),
        "path": path,
        "operation_id": op.get("operationId", ""),
        "summary": op.get("summary", "") or op.get("description", ""),
        "tags": list(op.get("tags") or []),
        "parameters": parameters,
        "body_schema": body_schema if isinstance(body_schema, dict) else {},
        "body_required": body_required,
        "success_code": success_code,
        "success_schema": success_schema if isinstance(success_schema, dict) else {},
        "error_code": error_code,
    }


def _pick_success(responses: dict) -> tuple[int, dict]:
    for code in _SUCCESS_CODES:
        if code in responses:
            return int(code), _response_schema(responses[code])
    for code in responses:
        if str(code).startswith("2"):
            return int(code), _response_schema(responses[code])
    return 200, {}


def _pick_error(responses: dict) -> int:
    for code in ("400", "422", "404", "409", "401", "403"):
        if code in responses:
            return int(code)
    return 400


def _response_schema(response) -> dict:
    if not isinstance(response, dict):
        return {}
    content = response.get("content")
    if isinstance(content, dict) and content:
        media = content.get("application/json") or next(iter(content.values()))
        if isinstance(media, dict):
            return media.get("schema") or {}
    return response.get("schema") or {}


# ============================================================
# schema → 示例
# ============================================================
def example_from_schema(schema) -> object:
    if not isinstance(schema, dict):
        return None
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]
    if "allOf" in schema:
        merged: dict = {}
        for part in schema["allOf"]:
            value = example_from_schema(part)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        return {
            name: example_from_schema(prop)
            for name, prop in (schema.get("properties") or {}).items()
        }
    if schema_type == "array":
        return [example_from_schema(schema.get("items") or {})]
    if schema_type == "integer":
        return int(schema.get("minimum", 1))
    if schema_type == "number":
        return float(schema.get("minimum", 1))
    if schema_type == "boolean":
        return True
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "date":
            return "2026-01-01"
        return "string"
    return None


def _find_boundary(schema: dict):
    """在 object schema 中找一个可越界的字段，返回 (field, value)。"""
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") == "integer" and "maximum" in prop:
            return name, int(prop["maximum"]) + 1
        if prop.get("type") == "integer" and "minimum" in prop:
            return name, int(prop["minimum"]) - 1
        if prop.get("type") == "string" and "maxLength" in prop:
            return name, "x" * (int(prop["maxLength"]) + 1)
        if prop.get("type") == "string" and "minLength" in prop and int(prop["minLength"]) > 0:
            return name, ""
    return None


# ============================================================
# endpoint → scenarios
# ============================================================
def endpoints_to_scenarios(endpoints: list[dict], base_url: str = "") -> list[dict]:
    scenarios: list[dict] = []
    for endpoint in endpoints:
        scenarios.extend(_endpoint_scenarios(endpoint, base_url))
    return scenarios


def _endpoint_scenarios(endpoint: dict, base_url: str) -> list[dict]:
    method = endpoint["method"]
    path = endpoint["path"]
    label = endpoint.get("summary") or endpoint.get("operation_id") or f"{method} {path}"
    tags = ["api", "swagger"] + [t for t in endpoint.get("tags", []) if t]
    tags = list(dict.fromkeys(tags))
    module = (endpoint.get("tags") or [""])[0]
    env = {"api": base_url} if base_url else {}

    positive_body = example_from_schema(endpoint.get("body_schema") or {})
    assertions = _success_assertions(endpoint)
    scenarios = [
        _scenario(
            title=f"{label} - 正常",
            endpoint=endpoint,
            tags=tags,
            module=module,
            env=env,
            priority="P0",
            body=positive_body if isinstance(positive_body, dict) else {},
            params=_param_examples(endpoint),
            assertions=assertions,
        )
    ]

    required = endpoint.get("body_required") or []
    if required:
        negative_body = copy.deepcopy(positive_body) if isinstance(positive_body, dict) else {}
        negative_body.pop(required[0], None)
        scenarios.append(
            _scenario(
                title=f"{label} - 缺少必填字段 {required[0]}",
                endpoint=endpoint,
                tags=tags,
                module=module,
                env=env,
                priority="P1",
                body=negative_body,
                params=_param_examples(endpoint),
                assertions=[{"type": "status_equals", "expected": endpoint.get("error_code", 400)}],
            )
        )
    else:
        required_params = [
            p for p in endpoint.get("parameters", [])
            if isinstance(p, dict) and p.get("required") and p.get("in") in ("path", "query")
        ]
        if required_params:
            params = _param_examples(endpoint)
            params.pop(required_params[0].get("name", ""), None)
            scenarios.append(
                _scenario(
                    title=f"{label} - 缺少必填参数 {required_params[0].get('name')}",
                    endpoint=endpoint,
                    tags=tags,
                    module=module,
                    env=env,
                    priority="P1",
                    body=positive_body if isinstance(positive_body, dict) else {},
                    params=params,
                    assertions=[{"type": "status_equals", "expected": 400}],
                )
            )

    boundary = _find_boundary(endpoint.get("body_schema") or {})
    if boundary:
        field, value = boundary
        boundary_body = copy.deepcopy(positive_body) if isinstance(positive_body, dict) else {}
        boundary_body[field] = value
        scenarios.append(
            _scenario(
                title=f"{label} - 边界值 {field}",
                endpoint=endpoint,
                tags=tags,
                module=module,
                env=env,
                priority="P2",
                body=boundary_body,
                params=_param_examples(endpoint),
                assertions=[{"type": "status_equals", "expected": endpoint.get("error_code", 400)}],
            )
        )

    return scenarios


def _success_assertions(endpoint: dict) -> list[dict]:
    assertions: list[dict] = [
        {"type": "status_equals", "expected": endpoint.get("success_code", 200)}
    ]
    schema = endpoint.get("success_schema") or {}
    if schema and schema.get("type") == "object":
        assertions.append({"type": "json_schema", "schema": schema})
        for name in (schema.get("properties") or {}):
            prop = schema["properties"][name]
            if isinstance(prop, dict) and ("example" in prop or "default" in prop or prop.get("enum")):
                expected = prop.get("example", prop.get("default", prop.get("enum", [None])[0]))
                assertions.append(
                    {"type": "json_field", "path": name, "expected": expected}
                )
    return assertions


def _param_examples(endpoint: dict) -> dict:
    params: dict = {}
    for param in endpoint.get("parameters", []) or []:
        if not isinstance(param, dict):
            continue
        location = param.get("in")
        name = param.get("name")
        if location not in ("query", "path") or not name:
            continue
        schema = param.get("schema") or {}
        params[name] = param.get("example", example_from_schema(schema))
    return params


def _scenario(*, title, endpoint, tags, module, env, priority, body, params, assertions) -> dict:
    api = {
        "method": endpoint["method"],
        "path": endpoint["path"],
        "headers": {"Content-Type": "application/json"} if body else {},
        "body": body or {},
        "params": params or {},
        "expected_status": endpoint.get("success_code", 200),
        "assertions": assertions,
    }
    return {
        "title": title,
        "description": f"{endpoint['method']} {endpoint['path']}（来自 Swagger）",
        "type": "api",
        "test_types": ["api"],
        "priority": priority,
        "acceptance_criteria": [],
        "tags": tags,
        "api_ref": f"{endpoint['method']} {endpoint['path']}",
        "api": api,
        "automation": {"manual": False, "ui": False, "api": True},
        "module": module,
        "env": env,
        "source": "swagger",
        "raw_text": f"{endpoint['method']} {endpoint['path']}",
    }
