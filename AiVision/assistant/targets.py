"""核验目标引用的原文来源和资源身份，模型提议不能直接变成操作依据。"""
import re
import unicodedata


CLARIFY_TARGET = "目前无法核验这个目标的对应关系。请提供完整摄像头或资源名称、标识，并确认所属部门和功能。"


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


def matches_name(text, resource):
    return any(normalized(text) == normalized(resource[field]) for field in ("target_name", "name", "identifier", "key")
               if resource.get(field))


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
    def __init__(self, question, plan, memory=None):
        self.question, self.plan, self.memory = question, plan, memory or {}
        self.references = plan.target_context.references if plan.target_context else []
        self.proposals = plan.target_context.bindings if plan.target_context else []
        self.candidates = {item["key"]: item for item in self.memory.get("last_read_resources", [])}
        self.searched = set()
        self.selectors = []
        self.needs_clarification = False
        bindings = {normalized(item["alias"]): item["resource"] for item in self.memory.get("target_bindings", [])}
        self.candidates.update((item["resource"]["key"], item["resource"]) for item in self.memory.get("target_bindings", []))
        declarations = {normalized(item.alias): item for item in self.proposals if valid_proposal(item, question)}
        if len(declarations) != len(self.proposals):
            self.needs_clarification = True
        self.selectors.extend(("name", item.target) for item in declarations.values())
        explicit_target = bool(declarations) or any(item.kind in {"named", "alias"} for item in self.references)
        for reference in self.references:
            if not reference.text.strip() or reference.text not in question:
                self.needs_clarification = True
                continue
            if reference.kind == "named":
                self.selectors.append(("name", reference.text))
            elif reference.kind == "alias":
                alias = normalized(reference.text)
                if alias in declarations:
                    self.selectors.append(("name", declarations[alias].target))
                elif alias in bindings:
                    self.selectors.append(("identity", resource_identity(bindings[alias])))
                else:
                    self.needs_clarification = True
            else:
                if reference.kind == "context":
                    deictic = re.fullmatch(r"(?:(?:它们|这些|那些|它|这|那|刚才|刚刚|之前|上述|上面|前面)(?:的|那|这)?(?:一|几)?(?:台|个|些)?(?:摄像头|相机|资源|目标|参数|阈值|配置|通道|保安室)?|(?:这|那)?两台)", reference.text)
                    available = bool(deictic)
                    # 本轮声明或明确点名优先于旧目标，“甲对应一号，查它”不能落到上次的二号。
                    if available and explicit_target:
                        continue
                else:
                    pending = self.memory.get("pending_task", {})
                    available = bool(pending) and pending.get("plan", {}).get("mode") == plan.mode
                resources = self.memory.get("last_read_resources", [])
                identities = {resource_identity(item) for item in resources}
                if reference.kind == "context":
                    if "两台" in reference.text:
                        available &= len(identities) == 2
                    elif len(identities) > 1 and not re.search(r"们|些|几", reference.text):
                        available = False
                if not available or not resources:
                    self.needs_clarification = True
                else:
                    self.selectors.extend(("identity", resource_identity(item)) for item in resources)
        # 已有别名出现在本轮时即参与核验，不能靠规划器漏填引用跳过绑定约束。
        if not self.references:
            mentioned = [resource for alias, resource in bindings.items()
                         if alias in normalized(question) and alias not in declarations]
            if len({resource_identity(item) for item in mentioned}) > 1:
                self.needs_clarification = True
            self.selectors.extend(("identity", resource_identity(item)) for item in mentioned)

    def observe(self, tool, result):
        if "error" in result:
            return
        if tool == "list_resources":
            for item in result.get("items", []):
                self.candidates[item["key"]] = item
                self.searched.add(item["key"])
            # 名称列表本身就是查询结果时，也必须核验目标，不能绕过后续的读取检查。
            if self.plan.query_tool == "list_resources" and self.selectors:
                if not result.get("items"):
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
        if self.selectors:
            self._check_keys([resource["key"]])

    def _check_keys(self, keys):
        permitted = set()
        for kind, value in self.selectors:
            matches = [resource for resource in self.candidates.values() if (
                matches_name(value, resource) if kind == "name" else resource_identity(resource) == value)]
            if len({resource_identity(resource) for resource in matches}) != 1:
                raise TargetClarification(CLARIFY_TARGET)
            permitted.update(resource["key"] for resource in matches)
        for key in keys:
            resource = self.candidates.get(key)
            explicit = resource is not None and any(resource.get(field) and resource[field] in self.question
                                                    for field in ("target_name", "name", "identifier", "key"))
            if resource is None or (key not in permitted if self.selectors else key not in self.searched and not explicit):
                raise TargetClarification(CLARIFY_TARGET)
