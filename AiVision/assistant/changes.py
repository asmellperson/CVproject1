"""把局部修改约束到用户原话与已发现目标，不以模型提交的 patch 作为授权。"""
from decimal import Decimal, InvalidOperation
import json
import re

from AiVision.departments.department_registry import DEPARTMENT_SPECS
from .intent import EDIT_VERBS, OPERATION_VERBS, deletion_target, positive_request, request_clauses, short_continuation, source_text, unquoted
from .targets import camera_name_variants, matches_name, normalized, resource_identity


# 字段标识和正式 Schema 标题始终可用；这里只维护常见业务说法，不保存配置值。
FIELD_NAMES = {
    "threshold": ("人体置信度", "人体检测置信度", "置信度", "阈值"),
    "cap_interval": ("检测间隔", "采样间隔"),
    "alarm_interval": ("报警间隔", "告警间隔", "报警冷却时间"),
    "fps": ("帧率", "采集帧率"),
    "name": ("名称", "改名", "重命名"),
    "max_restart": ("重连次数", "最大重启次数"),
    "roi_pos": ("ROI", "检测区域"),
    "enabled": ("摄像头开关", "启用摄像头", "开启摄像头", "停用摄像头", "关闭摄像头"),
    "enable": ("检测开关", "启用检测", "开启检测", "停用检测", "关闭检测"),
}
CHINESE_COUNTS = {value: index for index, value in enumerate("一二三四五六七八九十", 1)} | {"两": 2}
_ASSIGNMENT = re.compile(r"修改为|调整为|设置为|设定为|改为|改成|改到|设为|调为|调到|保持(?:为)?|^\s*[:=]")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


class ChangeScopeError(ValueError):
    """尚未产生写入的请求范围校验失败，允许模型在原调用预算内纠正。"""


def schema_fields(schema, node=None, path=(), depth=0):
    """沿正式 JSON Schema 展开对象字段，数组作为一个整体参数核验。"""
    if depth > 12:
        return
    node = dict(schema if node is None else node)
    if node.get("$ref", "").startswith("#/$defs/"):
        node = {**schema.get("$defs", {}).get(node["$ref"].split("/")[-1], {}), **node}
    properties = dict(node.get("properties", {}))
    for alternative in node.get("allOf", []) + node.get("anyOf", []):
        branch = alternative
        if branch.get("$ref", "").startswith("#/$defs/"):
            branch = schema.get("$defs", {}).get(branch["$ref"].split("/")[-1], {})
        properties.update(branch.get("properties", {}))
    if properties:
        for name, child in properties.items():
            yield from schema_fields(schema, child, (*path, name), depth + 1)
    elif path:
        yield path, node


def patch_fields(patch, path=()):
    for key, value in patch.items():
        if isinstance(value, dict) and value:
            yield from patch_fields(value, (*path, key))
        else:
            yield (*path, key)


def _literal_values(payload, *, string=False):
    """只读取原话中的明确字面值，不计算表达式或使用模型提交值补全缺项。"""
    values = []
    decoder = json.JSONDecoder()
    payload = payload.strip().removeprefix("分别").strip()
    while payload:
        try:
            number = _NUMBER.match(payload) if not string else None
            if number:
                value, end = Decimal(number[0]), number.end()
            elif string and not payload.startswith(('"', "“", "‘")):
                raise ValueError("字符串按原文字面值核验")
            else:
                value, end = decoder.raw_decode(payload)
        except ValueError:
            quoted = re.match(r"[“‘]([^”’]*)[”’]", payload)
            if quoted:
                value, end = quoted[1], quoted.end()
            elif payload.startswith(("空区域", "空列表", "空数组")):
                value, end = [], 3
            else:
                word = re.match(r"([^，,。；;]+)", payload)
                if not word:
                    break
                value, end = word[1].strip(), word.end()
        rest = payload[end:]
        # 单位不能被静默丢弃；具体字段的合法单位在比较时进一步核对。
        unit = re.match(r"\s*(%|毫秒|秒|ms\b|s\b|fps\b|帧(?:/秒)?|次)", rest, re.IGNORECASE)
        values.append((value, unit[1].lower() if unit else ""))
        if unit:
            rest = rest[unit.end():]
        if isinstance(value, Decimal) and re.match(r"\s*[a-zA-Z%\u4e00-\u9fff]", rest) and not re.match(
                r"\s*(?:、|和|与|及|或者|或|还是|至|到|即可|就行|就好|谢谢|请|吧|就这样)", rest):
            raise ChangeScopeError("目标值的单位或补充条件无法核验，尚未保存，请明确具体数值和单位。")
        separator = re.match(r"\s*(?:、|和|与|及|，|,)\s*", rest)
        if not separator:
            if re.match(r"\s*(?:或者|或|还是|至|到|[~+*/×−-])", rest):
                raise ChangeScopeError("目标值包含选择、范围或计算，尚未保存，请明确具体值。")
            break
        remainder = rest[separator.end():]
        if not re.match(r'[+\-\d\[\{"“‘]|true\b|false\b|null\b', remainder):
            break
        payload = remainder
    return values


def _same_value(actual, expected, unit, path, metadata):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return not unit and type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float, Decimal)):
        try:
            wanted = Decimal(str(expected))
            if unit == "%":
                if metadata.get("maximum") != 1 or metadata.get("minimum", 0) < 0:
                    return False
                wanted /= 100
            elif unit in {"毫秒", "ms", "秒", "s"}:
                description = str(metadata.get("description", "")) + str(metadata.get("title", ""))
                if "秒" not in description and path[-1] not in {"cap_interval", "alarm_interval"}:
                    return False
                if unit in {"毫秒", "ms"}:
                    wanted /= 1000
            elif unit:
                description = str(metadata.get("description", "")) + str(metadata.get("title", ""))
                if not (unit in {"fps", "帧", "帧/秒"} and path[-1] == "fps"
                        or unit == "次" and (path[-1] == "max_restart" or "次数" in description)):
                    return False
            return wanted.is_finite() and Decimal(str(actual)) == wanted
        except InvalidOperation:
            return False
    return not unit and type(actual) is type(expected) and actual == expected


def check_requested_values(text, fields, requested, schema, patch):
    metadata = dict(schema_fields(schema))
    groups = []
    for item in fields:
        if groups and re.fullmatch(r"[\s、和与及以的]*", text[groups[-1][-1][1]:item[0]]):
            groups[-1].append(item)
        else:
            groups.append([item])
    expected = {}
    for index, group in enumerate(groups):
        paths = [item[2] for item in group]
        if not requested.intersection(paths):
            continue
        end = groups[index + 1][0][0] if index + 1 < len(groups) else len(text)
        suffix = text[group[-1][1]:end]
        assignments = list(_ASSIGNMENT.finditer(unquoted(suffix)))
        payload = suffix[assignments[-1].end():].strip() if assignments else re.sub(
            r"^\s*(?:的)?(?:配置值|值)?\s*(?:分别|都|均|统一)?\s*(?:为|到|改|设)?\s*", "", suffix)
        values = _literal_values(payload, string=len(paths) == 1 and metadata[paths[0]].get("type") == "string")
        if len(paths) == 1 and metadata[paths[0]].get("type") == "boolean":
            boolean_text = payload.strip() or text[group[0][0]:group[-1][1]]
            if re.fullmatch(r"(?:关闭|停用|禁用|关|否)(?:检测|摄像头)?", boolean_text):
                values = [(False, "")]
            elif re.fullmatch(r"(?:开启|启用|打开|开|是)(?:检测|摄像头)?", boolean_text):
                values = [(True, "")]
        if len(values) == 1 and len(paths) > 1:
            values *= len(paths)
        if len(values) != len(paths):
            raise ChangeScopeError("无法逐项核验用户要求的目标值，尚未保存，请明确每个参数的具体值。")
        for path, value in zip(paths, values):
            if path not in requested:
                continue
            if path in expected and expected[path] != value:
                raise ChangeScopeError("同一参数有多个目标值，尚未保存，请明确最终值。")
            expected[path] = value
    for path in requested:
        actual = patch
        for key in path:
            actual = actual[key]
        if path not in expected or not _same_value(actual, *expected[path], path, metadata[path]):
            raise ChangeScopeError("修改值与用户明确要求不一致或无法核验，尚未保存。请按用户原话提交具体目标值，无法确认时先询问。")


class ChangePolicy:
    def __init__(self, question, plan, target_policy, memory=None):
        self.question, self.plan, self.target_policy = question, plan, target_policy
        self.pending = (memory or {}).get("pending_task", {})
        self.resources = dict(target_policy.candidates)
        self.searches = {}

    def scoped_request(self, resource=None):
        clauses = []
        identity = resource_identity(resource) if resource else None
        positive_identity = False
        for clause in request_clauses(self.question):
            if not clause.executable:
                continue
            mentioned = {resource_identity(item) for item in self.resources.values()
                         if any(normalized(item.get(key, "")) in normalized(clause.text)
                                for key in ("target_name", "name", "identifier") if item.get(key))}
            positive_identity |= identity in mentioned
            if identity is None or not mentioned or identity in mentioned:
                clauses.append(clause.text)
        if identity is not None and not positive_identity and any(
                resource_identity(item) == identity for kind, value in self.target_policy.selectors if kind == "name"
                for item in self.target_policy.matching_resources(kind, value)):
            # 出现在“保留 A”等非执行片段中的名称，不能为另一分句的修改提供目标授权。
            return ""
        return "，".join(clauses)

    def check_operation(self, tool, arguments):
        resource = self.resources.get(getattr(arguments, "camera_key", ""))
        text = self.scoped_request(resource)
        if not OPERATION_VERBS[tool].search(unquoted(text)) or short_continuation(self.question):
            # 仅处于等待补充状态的任务可使用历史操作；新的讨论或否定不能继承授权。
            if not self.is_continuation() or tool not in self.pending.get("plan", {}).get("operations", []):
                raise ChangeScopeError("当前用户请求无法核验此操作的执行意图，尚未执行，请明确具体操作。")
            text = positive_request(self.pending.get("request", ""))
        if tool != "undo_configuration" and re.match(r"(?:请)?(?:撤销|回滚|还原|恢复)", text):
            raise ChangeScopeError("撤销请求不能授权重新执行配置或删除，尚未执行。")
        if not text or not OPERATION_VERBS[tool].search(unquoted(text)):
            raise ChangeScopeError("当前用户请求没有明确授权此操作，尚未执行。")
        if tool == "delete_camera":
            self.check_delete_target(text, resource)

    def check_delete_target(self, text, resource):
        if resource is None:
            raise ChangeScopeError("删除目标尚未读取核验，尚未执行。")
        names = {normalized(resource[key]) for key in ("name", "target_name", "identifier", "key") if resource.get(key)}
        names.update(normalized(item["alias"]) for item in self.target_policy.memory.get("target_bindings", [])
                     if resource_identity(item["resource"]) == resource_identity(resource))
        # 普通指代只有在 TargetPolicy 已经核验唯一身份后才进入这里。
        names.update(normalized(item.text) for item in self.target_policy.references if item.kind == "context")
        if (self.is_continuation() and camera_name_variants(self.question) & names
                and any(resource_identity(item) == resource_identity(resource) for item in self.pending.get("candidates", []))
                and any(deletion_target(clause.text) is not None for clause in request_clauses(text))):
            return
        department = DEPARTMENT_SPECS.get(resource.get("department"))
        for clause in request_clauses(text):
            target = deletion_target(clause.text)
            if target is None:
                continue
            if department:
                for label in (department.display_name, department.name):
                    target = re.sub(re.escape(label), "", target, flags=re.IGNORECASE).strip().removeprefix("的").strip()
            if camera_name_variants(target) & names:
                return
        raise ChangeScopeError("无法从当前删除指令核验完整目标，尚未执行；讨论、记录查询和取消不能授权删除摄像头。")

    def is_continuation(self):
        references = self.plan.target_context.references if self.plan.target_context else []
        return bool(self.pending and (short_continuation(self.question)
                    or any(matches_name(self.question, item) for item in self.pending.get("candidates", []))
                    or any(item.kind == "pending" for item in references) and positive_request(self.question)))

    def observe(self, tool, result, arguments):
        if "error" in result:
            return
        if tool == "list_resources":
            self.resources.update((item["key"], item) for item in result.get("items", []))
            group = tuple(arguments.get(key) for key in ("kind", "department", "feature", "query", "parent_key"))
            self.searches.setdefault(group, {})[arguments.get("offset", 0)] = result
        elif tool == "read_configurations":
            self.resources.update((item["resource"]["key"], item["resource"]) for item in result.get("items", []))

    def request_for(self, resource):
        text = self.scoped_request(resource)
        if self.is_continuation() and self.pending.get("plan", {}).get("mode") == "change":
            if _NUMBER.fullmatch(text):
                # 直接补充数字仍需继承有效待办的字段，目标值只来自本轮原文。
                text = "改为" + text
            text = positive_request(self.pending.get("request", "")) + "，" + text
        # 资源名称中的“阈值”“检测间隔”等字样不是参数修改要求。
        for key in ("target_name", "name", "identifier"):
            if resource.get(key):
                text = re.sub(re.escape(source_text(resource[key])), "", text, count=1, flags=re.IGNORECASE)
        return text

    def check_patch(self, resource, patch):
        schema = resource.response().schema_definition
        reference = resource.reference.model_dump()

        def requested_fields(text):
            mentions = {}
            for path, metadata in schema_fields(schema):
                names = {".".join(path), path[-1], metadata.get("title", ""), *FIELD_NAMES.get(path[-1], ())}
                # enable 在报警渠道等嵌套对象中含义不同，不能共用检测开关的中文说法。
                if path[-1] == "enable" and len(path) > 1:
                    names = {".".join(path)}
                for name in names - {""}:
                    name = normalized(name)
                    if re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text, re.IGNORECASE):
                        mentions.setdefault(name, set()).add(path)
            occurrences = sorted((match.start(), match.end(), next(iter(paths)))
                                 for name, paths in mentions.items() if len(paths) == 1
                                 for match in re.finditer(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text, re.IGNORECASE))
            fields = []
            for start, end, path in sorted(occurrences, key=lambda item: (item[0], -item[1])):
                if not fields or start >= fields[-1][1]:
                    fields.append((start, end, path))
            requested = set()
            for verb in EDIT_VERBS.finditer(text):
                overlapping = [item for item in fields if item[0] < verb.end() and item[1] > verb.start()]
                if overlapping:
                    requested.update(item[2] for item in overlapping)
                    continue
                before = [index for index, item in enumerate(fields) if item[1] <= verb.start()]
                after = [index for index, item in enumerate(fields) if item[0] >= verb.end()]
                following = after[0] if after else None
                gap = text[verb.end():fields[following][0]] if following is not None else ""
                # “修改检测间隔”指向后面的字段；“阈值改为0.8”指向前面的字段。
                forward = following is not None and len(gap) < 80 and not re.search(r"[，,。；;\n\d]|为|成|到|一点", gap)
                anchor = following if forward else before[-1] if before else None
                if anchor is None:
                    continue
                requested.add(fields[anchor][2])
                direction = 1 if forward else -1
                neighbor = anchor + direction
                while 0 <= neighbor < len(fields):
                    left, right = sorted((anchor, neighbor))
                    conjunction = text[fields[left][1]:fields[right][0]]
                    if not re.fullmatch(r"[\s、和与及以的]*", conjunction):
                        break
                    requested.add(fields[neighbor][2])
                    anchor, neighbor = neighbor, neighbor + direction
            return requested, fields

        current = self.scoped_request(reference)
        for key in ("target_name", "name", "identifier"):
            if reference.get(key):
                current = re.sub(re.escape(source_text(reference[key])), "", current, count=1, flags=re.IGNORECASE)
        # 当前消息明确提出新参数时，不把上一项待澄清修改混入本轮授权。
        text = current
        requested, fields = requested_fields(text)
        if not requested:
            text = self.request_for(reference)
            requested, fields = requested_fields(text)
        submitted = set(patch_fields(patch))
        if not requested or submitted != requested:
            raise ChangeScopeError("修改字段与当前请求不一致，尚未保存。请按正式 Schema 只提交用户明确要求的全部参数；无法确认字段时先询问。")
        check_requested_values(text, fields, requested, schema, patch)

    @staticmethod
    def scope(resource):
        return resource.get("kind"), resource.get("department"), resource.get("feature")

    def check_targets(self, changes):
        text = positive_request(self.question)
        count_text = text
        for kind, value in self.target_policy.selectors:
            if kind == "name" and self.target_policy.matching_resources(kind, value):
                count_text = count_text.replace(normalized(value), "", 1)
        counts = {CHINESE_COUNTS.get(value, int(value) if value.isdigit() else None)
                  for value in re.findall(r"([一二两三四五六七八九十]|[1-9]\d*)\s*(?:台|个)(?:摄像头|相机|闸机|资源|通道)?", count_text)}
        count = next(iter(counts)) if len(counts) == 1 else None
        all_targets = bool(re.search(r"所有|全部|都(?:改|设|调)", count_text))
        selected = {change.resource_key for change in changes}
        scopes = {self.scope(self.resources[key]) for key in selected if key in self.resources}
        explicit = {item["key"] for kind, value in self.target_policy.selectors
                    for item in self.target_policy.matching_resources(kind, value) if self.scope(item) in scopes}
        explicit_identities = {resource_identity(self.resources[key]) for key in explicit if key in self.resources}
        if not all_targets and not (count and count > 1) and len(explicit_identities) <= 1:
            return
        expected = set(explicit)
        for group, pages in self.searches.items():
            page_resources = [item for page in pages.values() for item in page.get("items", [])]
            if not any(self.scope(item) in scopes for item in page_resources):
                continue
            query = normalized(group[3] or "")
            if query and query not in text:
                raise ChangeScopeError("批量搜索条件无法从用户请求核验，请按明确范围重新搜索全部目标，尚未保存。")
            offset, visited, keys, totals = 0, set(), set(), set()
            while offset is not None and offset in pages and offset not in visited:
                visited.add(offset)
                page = pages[offset]
                keys.update(item["key"] for item in page.get("items", []) if self.scope(item) in scopes)
                totals.add(page.get("total", len(page.get("items", []))))
                offset = page.get("next_offset")
            if offset is not None or len(totals) != 1 or len(keys) != next(iter(totals)):
                raise ChangeScopeError("批量目标尚未完整查询，请按 next_offset 查询所有分页后再提交，尚未保存。")
            expected.update(keys)
        if not expected or (count and len({resource_identity(self.resources[key]) for key in expected}) != count) or selected != expected:
            raise ChangeScopeError("批量目标与用户要求不完整，请读取全部目标并一次提交所有目标的局部修改，尚未保存。")
