"""把局部修改约束到用户原话与已发现目标，不以模型提交的 patch 作为授权。"""
import re

from .targets import matches_name, normalized, resource_identity


# 字段标识和正式 Schema 标题始终可用；这里只维护常见业务说法，不保存配置值。
FIELD_NAMES = {
    "threshold": ("人体置信度", "人体检测置信度", "置信度", "阈值"),
    "cap_interval": ("检测间隔", "采样间隔"),
    "alarm_interval": ("报警间隔", "告警间隔", "报警冷却时间"),
    "fps": ("帧率", "采集帧率"),
    "name": ("名称", "改名", "重命名"),
    "max_restart": ("重连次数", "最大重启次数"),
    "roi_pos": ("ROI", "检测区域"),
    "enabled": ("摄像头开关", "启用摄像头", "停用摄像头", "关闭摄像头"),
    "enable": ("检测开关", "启用检测", "停用检测", "关闭检测"),
}
CHINESE_COUNTS = {value: index for index, value in enumerate("一二三四五六七八九十", 1)} | {"两": 2}
EDIT_VERBS = re.compile(r"修改|调整|设置|设定|改为|改成|改到|调低|调高|提高|降低|保持|开启|关闭|启用|停用|重命名|改名|更新|改")


class ChangeScopeError(ValueError):
    """尚未产生写入的请求范围校验失败，允许模型在原调用预算内纠正。"""


def positive_request(question):
    # 否定与示例中的字段不能为同一条请求中的真实修改提供授权。
    return re.sub(r"(?:不要|别(?:修改|调整|改|动)|无需|不需要|禁止|不改|例如|比如|示例|假设|如果)[^，,。；;\n]*", "", normalized(question))


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


class ChangePolicy:
    def __init__(self, question, plan, target_policy, memory=None):
        self.question, self.plan, self.target_policy = question, plan, target_policy
        self.pending = (memory or {}).get("pending_task", {})
        self.resources = dict(target_policy.candidates)
        self.searches = {}

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
        text = positive_request(self.question)
        references = self.plan.target_context.references if self.plan.target_context else []
        candidates = self.pending.get("candidates", [])
        continuation = (any(item.kind == "pending" for item in references)
                        or any(matches_name(self.question, item) for item in candidates)
                        or re.fullmatch(r"(?:就|那就)?(?:改为|改成|设为|设置为)?\s*[+-]?\d+(?:\.\d+)?", text))
        if continuation and self.pending.get("plan", {}).get("mode") == "change":
            text = positive_request(self.pending.get("request", "")) + "，" + text
        # 资源名称中的“阈值”“检测间隔”等字样不是参数修改要求。
        for key in ("target_name", "name", "identifier"):
            if resource.get(key):
                text = text.replace(normalized(resource[key]), "", 1)
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
                    if re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text):
                        mentions.setdefault(name, set()).add(path)
            occurrences = sorted((match.start(), match.end(), next(iter(paths)))
                                 for name, paths in mentions.items() if len(paths) == 1
                                 for match in re.finditer(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", text))
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
            return requested

        current = positive_request(self.question)
        for key in ("target_name", "name", "identifier"):
            if reference.get(key):
                current = current.replace(normalized(reference[key]), "", 1)
        # 当前消息明确提出新参数时，不把上一项待澄清修改混入本轮授权。
        requested = requested_fields(current) or requested_fields(self.request_for(reference))
        submitted = set(patch_fields(patch))
        if not requested or submitted != requested:
            raise ChangeScopeError("修改字段与当前请求不一致，尚未保存。请按正式 Schema 只提交用户明确要求的全部参数；无法确认字段时先询问。")

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
