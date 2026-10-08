"""只读核对数据库实际结构与 ORM 声明，拒绝将结构差异当作正常启动。

检查列、类型、默认值、主键、索引、外键与 CHECK；必要的反射表示差异先做规范化。
本模块不执行 ALTER 或转换历史数据，结构不一致应由明确的离线迁移处理。
"""
import re

from sqlalchemy import CheckConstraint, String, UniqueConstraint, inspect


def _default(value):
    """规范化反射默认值的引号、括号、NULL 与数字表示，减少数据库表达差异造成的误判。"""
    if value is None:
        return None
    value = str(value).strip("()'\"").lower()
    if value == "null":
        return None
    try:
        return float(value)
    except ValueError:
        return value


def _type(column_type, dialect):
    """按当前数据库方言编译类型，忽略字符串继承排序规则并统一常见布尔/整数别名。"""
    if isinstance(column_type, String):
        # MySQL 反射可能显式携带继承的字符集/排序规则；它们不是 VARCHAR 长度等类型属性。
        column_type = column_type.copy()
        column_type.collation = None
        if hasattr(column_type, "charset"):
            column_type.charset = None
    value = str(column_type.compile(dialect=dialect)).upper()
    return {"BOOL": "BOOLEAN", "TINYINT(1)": "BOOLEAN", "INTEGER": "INT"}.get(value, value)


def _expression(value):
    """去掉表达式空白、标识符引号和括号并转小写，供约束文本比较使用。"""
    return re.sub(r"[\s`\"()]+", "", str(value)).lower()


def assert_table_matches(connection, table, *, actual_name=None):
    """核对列、类型、空值、服务端默认值、主键、索引、外键和 CHECK 约束。"""
    inspector = inspect(connection)
    name = actual_name or table.name
    columns = {column["name"]: column for column in inspector.get_columns(name)}
    errors = []
    if set(columns) != set(table.columns.keys()):
        errors.append(f"列不一致: missing={sorted(set(table.columns.keys()) - set(columns))}, "
                      f"extra={sorted(set(columns) - set(table.columns.keys()))}")
    for column in table.columns:
        actual = columns.get(column.name)
        if actual is None:
            continue
        if _type(column.type, connection.dialect) != _type(actual["type"], connection.dialect):
            errors.append(f"{column.name}: 类型不一致")
        for attribute in ("charset", "collation"):
            expected = getattr(column.type, attribute, None)
            if expected is not None and expected != getattr(actual["type"], attribute, None):
                errors.append(f"{column.name}: {attribute} 不一致")
        if actual["nullable"] != column.nullable:
            errors.append(f"{column.name}: nullable 不一致")
        expected_default = column.server_default.arg if column.server_default is not None else None
        if _default(actual["default"]) != _default(expected_default):
            errors.append(f"{column.name}: server_default 不一致")
    if inspector.get_pk_constraint(name)["constrained_columns"] != [c.name for c in table.primary_key]:
        errors.append("主键不一致")
    expected_indexes = {(tuple(c.name for c in index.columns), bool(index.unique)) for index in table.indexes}
    reflected_indexes = inspector.get_indexes(name)
    actual_indexes = {(tuple(index["column_names"]), bool(index["unique"])) for index in reflected_indexes
                      if not index.get("duplicates_constraint")}
    # MySQL 自动为外键建立普通索引，也用索引实现 UNIQUE 约束。
    expected_unique = {tuple(c.name for c in item.columns) for item in table.constraints
                       if isinstance(item, UniqueConstraint)}
    actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
    actual_unique -= {columns for columns, unique in expected_indexes if unique}
    if expected_unique != actual_unique:
        errors.append("唯一约束不一致")
    if connection.dialect.name == "mysql":
        implicit = {(tuple(c.name for c in fk.columns), False) for fk in table.foreign_key_constraints}
        implicit.update((columns, True) for columns in expected_unique)
        actual_indexes -= implicit - expected_indexes
    if expected_indexes != actual_indexes:
        errors.append("索引不一致")
    expected_fks = {(tuple(c.name for c in fk.columns), fk.referred_table.name,
                     tuple(e.column.name for e in fk.elements), fk.ondelete) for fk in table.foreign_key_constraints}
    actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]),
                   fk.get("options", {}).get("ondelete")) for fk in inspector.get_foreign_keys(name)}
    if expected_fks != actual_fks:
        errors.append("外键不一致")
    expected_checks = {_expression(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    actual_checks = {_expression(c["sqltext"]) for c in inspector.get_check_constraints(name)}
    if expected_checks != actual_checks:
        errors.append("CHECK 约束不一致")
    if errors:
        raise ValueError(f"{name}: {'; '.join(errors)}；请先执行对应版本的离线迁移")
