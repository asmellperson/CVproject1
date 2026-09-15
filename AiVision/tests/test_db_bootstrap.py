"""全新进程中必须先发现功能 ORM，再对空数据库建表和核验。"""
import subprocess
import sys
import textwrap

from test_alarm_device_package import isolated_environment


def test_fresh_schema_bootstrap_discovers_all_feature_tables_before_create_all(tmp_path):
    program = textwrap.dedent("""
        from contextlib import ExitStack
        from pathlib import Path
        import sys
        from unittest.mock import patch

        from sqlalchemy import create_engine, event, inspect

        assert not any(name.startswith('AiVision.features') for name in sys.modules)
        from AiVision.core import db, schema
        from AiVision import features
        assert not features._discovered and features._REGISTRY == {}
        assert not db.Base.metadata.tables
        assert not any(name.startswith('AiVision.features.') and name.endswith('.orm')
                       for name in sys.modules)

        expected = {
            'blocks', 'detect_door', 'detect_face', 'detect_human',
            'detect_logistics_single_person', 'detect_phone', 'recognize_face',
        }
        database = Path(sys.argv[1]) / 'fresh.sqlite'
        assert not database.exists()
        engine = create_engine('sqlite:///' + str(database))
        assert inspect(engine).get_table_names() == []
        creation_snapshots = []

        def before_create(metadata, connection, **kwargs):
            # Do not call all_specs here: the observer must not perform discovery itself.
            assert features._discovered, 'feature discovery must precede create_all'
            assert set(features._REGISTRY) == expected
            tables = {spec.orm_class.__table__ for spec in features._REGISTRY.values()}
            assert len(tables) == len(expected)
            for table in tables:
                assert metadata.tables[table.name] is table
            assert tables <= set(kwargs['tables'])
            creation_snapshots.append({table.name for table in tables})

        attempts = []
        def forbid(*args, **kwargs):
            attempts.append('external operation')
            raise AssertionError('bootstrap must only use the temporary SQLite database')

        event.listen(db.Base.metadata, 'before_create', before_create)
        try:
            with ExitStack() as stack:
                for target in ('pymysql.connect', 'socket.create_connection',
                               'socket.socket.connect', 'socket.socket.connect_ex',
                               'requests.sessions.Session.request', 'dotenv.load_dotenv',
                               'threading.Thread.start', 'multiprocessing.process.BaseProcess.start'):
                    stack.enter_context(patch(target, side_effect=forbid))
                stack.enter_context(patch.object(db, 'get_engine', return_value=engine))
                discover = stack.enter_context(patch.object(features, 'all_specs', wraps=features.all_specs))
                verify = stack.enter_context(patch.object(schema, 'assert_table_matches',
                                                         wraps=schema.assert_table_matches))
                # Real metadata DDL and real schema reflection/validation; only the engine is isolated.
                db.ensure_schema_ready()
                discover.assert_called_once_with()
                assert len(creation_snapshots) == 1
                assert creation_snapshots[0] <= set(inspect(engine).get_table_names())
                checked = [call.args[1] for call in verify.call_args_list]
                for spec in features._REGISTRY.values():
                    assert checked.count(spec.orm_class.__table__) == 1
                assert attempts == []
        finally:
            event.remove(db.Base.metadata, 'before_create', before_create)
            engine.dispose()
    """)
    result = subprocess.run(
        [sys.executable, '-c', program, str(tmp_path)], cwd=tmp_path,
        env=isolated_environment(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '加载 features.' not in result.stderr
