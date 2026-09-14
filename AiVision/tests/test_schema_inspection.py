"""MySQL 反射形式不能被误报成类型变化，明确声明的约束仍须核验。"""
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import mysql

from AiVision.core import schema


def inspect_table(monkeypatch, expected, actual, *, nullable=True, default=None):
    table = Table("example", MetaData(), Column("id", Integer, primary_key=True), Column("value", expected))
    inspector = SimpleNamespace(
        get_columns=lambda _: [
            {"name": "id", "type": mysql.INTEGER(), "nullable": False, "default": None},
            {"name": "value", "type": actual, "nullable": nullable, "default": default},
        ],
        get_pk_constraint=lambda _: {"constrained_columns": ["id"]},
        get_indexes=lambda _: [], get_unique_constraints=lambda _: [],
        get_foreign_keys=lambda _: [], get_check_constraints=lambda _: [],
    )
    monkeypatch.setattr(schema, "inspect", lambda _: inspector)
    schema.assert_table_matches(SimpleNamespace(dialect=mysql.dialect()), table)


def test_unspecified_charset_and_collation_do_not_change_varchar_type(monkeypatch):
    actual = mysql.VARCHAR(255, charset="utf8mb4", collation="utf8mb4_unicode_ci")
    inspect_table(monkeypatch, String(255), actual)
    assert actual.charset == "utf8mb4" and actual.collation == "utf8mb4_unicode_ci"


def test_explicit_collation_is_checked(monkeypatch):
    inspect_table(monkeypatch, String(255, collation="utf8mb4_bin"), mysql.VARCHAR(255, collation="utf8mb4_bin"))
    with pytest.raises(ValueError, match="collation 不一致"):
        inspect_table(monkeypatch, String(255, collation="utf8mb4_bin"), mysql.VARCHAR(255, collation="utf8mb4_unicode_ci"))


@pytest.mark.parametrize("actual,options,error", [
    (mysql.VARCHAR(128), {}, "类型"),
    (mysql.TEXT(), {}, "类型"),
    (mysql.VARCHAR(255), {"nullable": False}, "nullable"),
    (mysql.VARCHAR(255), {"default": "'0'"}, "server_default"),
])
def test_real_type_default_and_nullability_changes_still_fail(monkeypatch, actual, options, error):
    with pytest.raises(ValueError, match=error):
        inspect_table(monkeypatch, String(255), actual, **options)


def test_unsigned_integer_is_not_normalized_away():
    dialect = mysql.dialect()
    assert schema._type(Integer(), dialect) != schema._type(mysql.INTEGER(unsigned=True), dialect)
