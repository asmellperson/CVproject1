"""核验目标引用的原文来源和资源身份，模型提议不能直接变成操作依据。"""
import re
import unicodedata

from AiVision.departments.department_registry import DEPARTMENT_SPECS
from .intent import feature_state


CLARIFY_TARGET = "目前无法核验这个目标的对应关系。请提供完整摄像头或资源名称、标识，并确认所属部门和功能。"
CONTEXT_REFERENCE = re.compile(
    r"(?:(?:它们|这些|那些|它|这|那|刚才|刚刚|之前|上述|上面|前面)"
    r"(?:的|那|这)?(?:一|几)?(?:台|个|些)?"
    r"(?:摄像头|相机|资源|目标|参数|阈值|配置|通道|保安室)?|(?:这|那)?两台)"
)


class TargetClarification(ValueError):
    """目标身份不能核验时结束本轮并澄清，不让模型继续猜测标识。"""


def normalized(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def resource_identity(resource):
    # camera 和普通 feature 配置属于同一台物理摄像头，但不能跨部门或凭名称合并。
    parts = resource["key"].split(":")
    if (resource.get("kind") in {"camera", "feature"} and parts[-1].isdigit()
            and ((parts[0] == "camera" and len(parts) == 2) or (parts[0] == "feature" and len(parts) == 3))):
        return "camera", resource.get("department"), int(parts[-1])
    return resource.get("kind"), resource.get("department"), resource["key"]


def reference_scope(text):
    value = normalized(text)
    for spec in DEPARTMENT_SPECS.values():
        for label in (spec.display_name, spec.name):
            if value.startswith(normalized(label)):
                return spec.name, value[len(label):].strip().removeprefix("的").strip()
    return None, value


def matches_name(text, resource):
    department, value = reference_scope(text)
    if department is not None and department != resource.get("department"):
        return False
    return any(normalized(resource[field]) in {normalized(text), value} for field in ("target_name", "name", "identifier", "key")
               if resource.get(field))


def camera_name_variants(text):
    """类别词可在名称前后，仍只生成完整名称候选，不做前缀或模糊身份匹配。"""
    _department, value = reference_scope(text)
    values = [value]
    for pattern in (r"(?:摄像头|摄像机|相机)\s*(.+)", r"(.+?)\s*(?:摄像头|摄像机|相机)"):
        match = re.fullmatch(pattern, value)
        if match:
            values.append(match[1].strip())
    for item in list(values):
        if len(item) > 2 and (item[0], item[-1]) in {('“', '”'), ('‘', '’'), ('"', '"'), ("'", "'")}:
            values.append(item[1:-1].strip())
    return set(values) - {""}


def matching_named_resources(text, resources):
    resources = list(resources)
    exact = [item for item in resources if matches_name(text, item)]
    if exact:
        return exact
    department, _value = reference_scope(text)
    variants = camera_name_variants(text)
    return [item for item in resources if item.get("kind") in {"camera", "feature"}
            and (department is None or item.get("department") == department)
            and any(normalized(item[field]) in variants for field in ("target_name", "name", "identifier", "key")
                    if item.get(field))]


def feature_labels(item):
    label = normalized(item["label"])
    return {normalized(item["name"]), label, re.sub(r"(?:检测|功能)$", "", label)} - {""}


def mentioned_features(question, features):
    """业务目录的“检测”后缀可省略；重叠名称优先保留更完整的功能名。"""
    text = normalized(question)
    matches = []
    for item in features:
        for value in feature_labels(item):
            pattern = re.escape(value)
            if re.fullmatch(r"[a-z0-9_]+", value):
                pattern = r"(?<![a-z0-9_])" + pattern + r"(?![a-z0-9_])"
            matches.extend((match.start(), match.end(), item["name"]) for match in re.finditer(pattern, text))
    return {feature for start, end, feature in matches if not any(
        other_start <= start and other_end >= end and other_end - other_start > end - start
        for other_start, other_end, _feature in matches)}


def valid_proposal(proposal, question):
    if not all(value.strip() for value in (proposal.alias, proposal.target, proposal.evidence)):
        return False
    if proposal.evidence not in question or proposal.alias not in proposal.evidence or proposal.target not in proposal.evidence:
        return False
    if normalized(proposal.alias) == normalized(proposal.target):
        return False
    # 保留声明前同一分句的否定词，避免只截取“甲对应一号”而丢掉前面的“不要”。
    position = question.index(proposal.evidence)
    clause_prefix = re.split(r"[。！？；;\n]", question[:position])[-1]
    clause_suffix = re.split(r"[。！？；;\n]", question[position + len(proposal.evidence):])[0]
    if re.search(r"不要|不是|不对应|取消绑定|解除绑定|示例|例如|假设|如果", clause_prefix + proposal.evidence):
        return False
    if re.search(r"不成立|不对|错误的|不是|不是真的", clause_suffix):
        return False
    boundary = r'''(?=$|[\s，,。！？!?；;：:“”‘’"'）)\]])'''
    if clause_suffix and not re.match(boundary, clause_suffix):
        return False
    alias, target = re.escape(proposal.alias), re.escape(proposal.target)
    quote = r'''[“”‘’"']*'''

    def pair(value):
        return quote + value + quote
    # 两个名称共同出现不能证明绑定，必须有用户原话中的正向命名关系。
    patterns = (
        pair(alias) + r"\s*(?:对应|代表|指的是|就是|是)\s*" + pair(target),
        pair(target) + r"\s*的?(?:别名|代号|简称)\s*(?:是|为|叫|叫作|称为)?\s*" + pair(alias),
        r"(?:把|将)\s*" + pair(target) + r"\s*(?:称为|叫作|叫做|记作|简称为|称作)\s*" + pair(alias),
    )
    return any(re.search(pattern + boundary, proposal.evidence) for pattern in patterns)


def verified_bindings(proposals, question, resources):
    result = []
    for proposal in proposals:
        if not valid_proposal(proposal, question):
            continue
        matches = [resource for resource in resources if matches_name(proposal.target, resource)]
        if len({resource_identity(resource) for resource in matches}) == 1:
            result.append({"alias": proposal.alias, "resource": dict(matches[0])})
    return result


class TargetPolicy:
    def __init__(self, question, plan, memory=None, *, source_question=None, capabilities=None):
        self.question, self.plan, self.memory = question, plan, memory or {}
        self.references = plan.target_context.references if plan.target_context else []
        self.proposals = plan.target_context.bindings if plan.target_context else []
        self.candidates = {item["key"]: item for item in self.memory.get("last_read_resources", [])}
        self.searched = set()
        self.selectors = []
        self.reference_departments = set()
        self.context_sizes = set()
        self.needs_clarification = False
        self.inventory = plan.mode == "query" and plan.query_tool == "list_resources" and bool(re.search(r"摄像头|摄像机|相机", question))
        self.query_feature = None
        self.query_department = None
        self.query_feature_labels = set()
        self.feature_enabled = None
        if self.inventory and capabilities:
            departments = [spec.name for spec in DEPARTMENT_SPECS.values()
                           if any(normalized(label) in normalized(question) for label in
                                  (spec.name, spec.display_name, spec.display_name.removesuffix("事业部")))]
            features = mentioned_features(question, capabilities.get("features", []))
            if len(departments) == 1:
                self.query_department = departments[0]
                self.reference_departments.add(self.query_department)
            if len(features) == 1:
                self.query_feature = next(iter(features))
                self.query_feature_labels = next(feature_labels(item) for item in capabilities["features"] if item["name"] == self.query_feature)
            elif len(features) > 1:
                self.needs_clarification = True
            try:
                self.feature_enabled = feature_state(question)
            except ValueError:
                self.needs_clarification = True
        bindings = {normalized(item["alias"]): item["resource"] for item in self.memory.get("target_bindings", [])}
        self.candidates.update((item["resource"]["key"], item["resource"]) for item in self.memory.get("target_bindings", []))
        declarations = {normalized(item.alias): item for item in self.proposals
                        if valid_proposal(item, source_question if source_question is not None else question)}
        if len(declarations) != len(self.proposals):
            self.needs_clarification = True
        self.selectors.extend(("name", item.target) for item in declarations.values())
        contextual = []
        for reference in self.references:
            if not reference.text.strip() or reference.text not in question:
                self.needs_clarification = True
                continue
            department, literal = reference_scope(reference.text)
            if department is not None:
                self.reference_departments.add(department)
            if department is not None and not literal:
                continue
            # 模型的 kind 只是提议；已核验别名和有确定语法的指代按真实证据解析。
            if literal in declarations:
                self.selectors.append(("name", declarations[literal].target))
            elif literal in bindings:
                self.selectors.append(("identity", resource_identity(bindings[literal])))
            elif reference.kind in {"named", "context"} and CONTEXT_REFERENCE.fullmatch(literal):
                contextual.append(("context", literal))
            elif reference.kind == "named":
                self.selectors.append(("name", reference.text))
            elif reference.kind == "pending":
                contextual.append(("pending", literal))
            else:
                self.needs_clarification = True
        # 只有范围或指代时，也不能漏掉本轮明确提到的已核验别名而退回最近目标。
        if not self.selectors:
            mentioned = [resource for alias, resource in bindings.items()
                         if alias in normalized(question) and alias not in declarations]
            if len({resource_identity(item) for item in mentioned}) > 1:
                self.needs_clarification = True
            self.selectors.extend(("identity", resource_identity(item)) for item in mentioned)
        for kind, literal in contextual:
            camera_only = kind == "context" and bool(re.search(r"摄像头|相机", literal))
            if kind == "pending":
                pending = self.memory.get("pending_task", {})
                if not pending or pending.get("plan", {}).get("mode") != plan.mode:
                    self.needs_clarification = True
                    continue
                selected = [item for item in matching_named_resources(literal, pending.get("candidates", []))
                            if not self.reference_departments or item.get("department") in self.reference_departments]
                if selected:
                    # 候选来自真实查询，只接受本轮完整名称选择；配置与版本仍须重新读取。
                    if len({resource_identity(item) for item in selected}) != 1:
                        self.needs_clarification = True
                    self.candidates.update((item["key"], item) for item in selected)
                    self.selectors.extend(("identity", resource_identity(item)) for item in selected)
                    continue
            else:
                size = 2 if "两台" in literal else None if re.search(r"们|些|几", literal) else 1
                if size is not None:
                    self.context_sizes.add((size, camera_only))
            # 先解析本轮全部明确目标，不能因指代排在名称前面而套用旧摄像头。
            if not self.selectors:
                resources = [item for item in self.memory.get("last_read_resources", [])
                             if not self.reference_departments or item.get("department") in self.reference_departments]
                if camera_only:
                    cameras = [item for item in resources if resource_identity(item)[0] == "camera"]
                    resources = cameras or resources
                if not resources or (kind == "context" and size is not None
                                     and len({resource_identity(item) for item in resources}) != size):
                    self.needs_clarification = True
                self.selectors.extend(("identity", resource_identity(item)) for item in resources)

    def observe(self, tool, result):
        if "error" in result:
            return
        if tool == "list_resources":
            if self.inventory and self.query_feature and any(item.get("feature") != self.query_feature for item in result.get("items", [])):
                raise ValueError("查询结果没有保留用户指定的功能范围，不能作为摄像头统计结果")
            for item in result.get("items", []):
                self.candidates[item["key"]] = item
                self.searched.add(item["key"])
            # 名称列表本身就是查询结果时，也必须核验目标，不能绕过后续的读取检查。
            if self.plan.query_tool == "list_resources" and (self.selectors or self.reference_departments):
                if self.selectors and not result.get("items"):
                    raise TargetClarification(CLARIFY_TARGET)
                self._check_keys([item["key"] for item in result["items"]])
        elif tool == "read_configurations":
            self.candidates.update((item["resource"]["key"], item["resource"]) for item in result.get("items", []))

    def check(self, name, args):
        if name in {"capabilities", "ask_user"}:
            return
        if self.needs_clarification:
            raise TargetClarification(CLARIFY_TARGET)
        if name == "read_configurations":
            keys = args.resource_keys
        elif name == "update_configurations":
            keys = [change.resource_key for change in args.changes]
        elif name == "delete_camera":
            keys = [args.camera_key]
        elif name == "bind_camera":
            keys = [args.camera_key, args.parent_key]
        else:
            return
        self._check_keys(keys)

    def check_audited_resource(self, resource):
        # 撤销仍以会话内可访问的真实审计为依据；若本轮指定目标，审计不能指向另一台。
        if self.needs_clarification:
            raise TargetClarification(CLARIFY_TARGET)
        self.candidates[resource["key"]] = resource
        if self.selectors or self.reference_departments:
            self._check_keys([resource["key"]])

    def matching_resources(self, kind, value):
        resources = [resource for resource in self.candidates.values()
                     if not self.reference_departments or resource.get("department") in self.reference_departments]
        return matching_named_resources(value, resources) if kind == "name" else [
            resource for resource in resources if resource_identity(resource) == value]

    def search_arguments(self, args):
        if not self.inventory:
            return args
        updates = {}
        if self.query_feature:
            updates["kind"] = "camera"
        if self.query_department:
            updates["department"] = self.query_department
        if self.query_feature:
            updates["feature"] = self.query_feature
            scope_names = self.query_feature_labels | {normalized(DEPARTMENT_SPECS[self.query_department].display_name)
                           if self.query_department else "", "摄像头", "摄像机", "相机"}
            if not self.selectors and (normalized(args.query) in scope_names or normalized(args.query) not in normalized(self.question)):
                updates["query"] = ""
        if updates.get("feature") or args.feature:
            updates["feature_enabled"] = self.feature_enabled
        return args.model_copy(update=updates)

    def _check_keys(self, keys):
        permitted, identities = set(), set()
        for kind, value in self.selectors:
            matches = self.matching_resources(kind, value)
            if len({resource_identity(resource) for resource in matches}) != 1:
                raise TargetClarification(CLARIFY_TARGET)
            permitted.update(resource["key"] for resource in matches)
            identities.update(resource_identity(resource) for resource in matches)
        cameras = {item for item in identities if item[0] == "camera"}
        if any(len(cameras or identities if camera_only else identities) != size
               for size, camera_only in self.context_sizes):
            raise TargetClarification(CLARIFY_TARGET)
        for key in keys:
            resource = self.candidates.get(key)
            if resource is not None and self.reference_departments and resource.get("department") not in self.reference_departments:
                raise TargetClarification(CLARIFY_TARGET)
            explicit = resource is not None and any(resource.get(field) and resource[field] in self.question
                                                    for field in ("target_name", "name", "identifier", "key"))
            if resource is None or (key not in permitted if self.selectors else key not in self.searched and not explicit):
                raise TargetClarification(CLARIFY_TARGET)
