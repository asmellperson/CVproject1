"""从用户原话划定有效指令片段，供分类、工具核验和待办控制共同使用。"""
from dataclasses import dataclass
import re
import unicodedata


EDIT_VERBS = re.compile(r"修改|调整|设置|设定|改为|改成|改到|调低|调高|提高|降低|保持|开启|关闭|启用|停用|重命名|改名|更新|改")
OPERATION_VERBS = {
    "update_configurations": EDIT_VERBS,
    "delete_camera": re.compile(r"删除|删掉|删去|继续删"),
    "add_camera": re.compile(r"添加|新增|新建|创建|建档|接入"),
    "bind_camera": re.compile(r"绑定|加入|添加.+(?:到|进)"),
    "undo_configuration": re.compile(r"撤销|回滚|还原|恢复.+(?:配置|参数)"),
}
_NON_EXECUTION = re.compile(
    r"不要|(?<!分)别(?:修改|调整|改|动|删|执行|操作|做)|无需|不需要|禁止|不能|不用|不改|不删|先不|暂不|保留|"
    r"例如|比如|示例|假设|如果|假如|仅当|除非|是否|能否|可否|能不能|怎么|如何|"
    r"什么意思|意味着|会怎样|有什么|好不好|行不行|可不可以|只是.*(?:例子|举例)|"
    r"不是我的意思|先别做|缓一缓|明天再说|以后再说|前先|之前|"
    r"是.*(?:昨天|以前|之前|过去).*(?:操作|做的事)|今天只查|查一下|"
    r"^(?:请|帮我)?(?:查询|查看|统计|搜索|列出|介绍|解释|请问|咨询)|[?？]|(?:吗|么|呢)$"
)
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|“[^”]*”|‘[^’]*’|\x27[^\x27]*\x27')
_NEGATIVE_STATE = re.compile(r"(?:尚未|没有|未|没|不曾)(?:启用|开启|打开)|停用|关闭|禁用")
_POSITIVE_STATE = re.compile(r"(?:已)?(?:启用|开启|打开)")


def source_text(value):
    # 保留字符串值的大小写，字段和名称比较可另用忽略大小写匹配。
    return unicodedata.normalize("NFKC", value).strip()


def unquoted(value):
    return _QUOTED.sub(lambda match: " " * len(match[0]), value)


@dataclass(frozen=True)
class RequestClause:
    text: str

    @property
    def instruction(self):
        return unquoted(self.text)

    @property
    def executable(self):
        text = self.instruction.strip()
        if _NON_EXECUTION.search(text):
            return False
        if re.search(r"(?:删除|删掉|改为|改成|修改|调整).*(?:撤销|取消|作废|先别|先缓)", text):
            return False
        return not re.search(r"取消|作废|清除.*待办|不改了|不动了", text)


def request_clauses(question):
    """只在引号和 JSON 容器之外分句，避免拆坏名称、数组和结构化目标值。"""
    text = source_text(question)
    start, quote, escaped, depth = 0, None, False, 0
    pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    for index, character in enumerate(text):
        if quote:
            if character == quote and not escaped:
                quote = None
            escaped = character == "\\" and not escaped
            continue
        if character in pairs:
            quote = pairs[character]
        elif character in "[{(":
            depth += 1
        elif character in "]})":
            depth = max(0, depth - 1)
        elif not depth and character in ",，。;；\n!?！？":
            end = index + 1 if character in "?？" else index
            if text[start:end].strip():
                yield RequestClause(text[start:end].strip())
            start = index + 1
    if text[start:].strip():
        yield RequestClause(text[start:].strip())


def positive_request(question):
    return "，".join(clause.text for clause in request_clauses(question) if clause.executable)


def deletion_target(question):
    clauses = list(request_clauses(question))
    if len(clauses) != 1 or not clauses[0].executable:
        return None
    text = clauses[0].text
    polite = r"(?:请|麻烦|帮我|请帮我|麻烦帮我)?\s*"
    match = re.fullmatch(polite + r"(?:删除|删掉|删去)\s*(.+)", text)
    if match is None:
        match = re.fullmatch(polite + r"(?:把|将)\s*(.+?)\s*(?:删除|删掉|删去)", text)
    return match[1].strip() if match else None


def cancellation_request(question, *, has_pending=False):
    """取消待补充任务与撤销已经保存的配置分开；混合指令只撤销旧待办。"""
    clauses = list(request_clauses(question))
    cancelled = False
    remaining = []
    for clause in clauses:
        text = clause.instruction.strip()
        control = bool(re.search(r"取消|作废|清除.*待办|不改了|不动了", text))
        if (has_pending and not re.search(r"已保存|已完成|操作记录|保存记录", text)
                and re.match(r"(?:请)?撤销(?:刚才|上一|这个|这次|待办)", text)):
            control = True
        # “怎么取消”“取消报警”以及资源名称中的字样不是取消当前待办的指令。
        refers_pending = bool(re.search(r"刚才|上一|待办|这件事|那件事|这次|本次|当前任务|不改了|不动了", text))
        discussion = re.search(
            r"不要|无需|不需要|不用|不能|不取消|先不|暂不|别(?:取消|撤销|作废|清除)|"
            r"怎么|如何|是否|能否|例如|比如|示例|假设|如果|假如|好不好|行不行|[?？]|(?:吗|呢)$|"
            r"^(?:请|帮我)?(?:查询|查看|统计|搜索|列出|介绍|解释|请问|咨询)", text,
        )
        if control and refers_pending and not discussion:
            cancelled = True
        elif clause.executable and any(pattern.search(text) for pattern in OPERATION_VERBS.values()):
            remaining.append(clause)
    return cancelled, cancelled and not remaining


def short_continuation(question):
    return re.fullmatch(
        r"(?:就|那就)?(?:(?:改为|改成|设为|设置为)?\s*[+-]?\d+(?:\.\d+)?|继续|继续删|继续执行|执行|确认|确定|确定执行|是的|好的)[。!！\s]*",
        source_text(question),
    ) is not None


def feature_state(question):
    """根据用户明确包含或排除的状态求集合，再转换为工具使用的三态条件。"""
    included, excluded = set(), set()
    all_states = False
    for clause in request_clauses(question):
        text = clause.instruction
        negatives = list(_NEGATIVE_STATE.finditer(text))
        remainder = _NEGATIVE_STATE.sub(" ", text)
        positives = list(_POSITIVE_STATE.finditer(remainder))
        states = ({False} if negatives else set()) | ({True} if positives else set())
        if re.search(r"不要|不包括|不包含|排除|不算|别把", text):
            excluded.update(states)
            continue
        if re.search(r"(?:包括|包含).*?(?:未|没|停用|关闭|禁用)|无论是否|不管是否|不论是否|所有状态|全部状态", text):
            all_states = True
        included.update(states)
    states = ({True, False} if all_states else included or {True}) - excluded
    if len(states) == 2:
        return None
    if len(states) == 1:
        return next(iter(states))
    raise ValueError("摄像头启用状态条件互相冲突，请明确查询已启用、未启用还是全部状态")
