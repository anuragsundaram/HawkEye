import sqlite3
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app import app
from app.database.common.adapters import get_adapter
from app.database.common import registration
from app.database.oracle.views import top as oracle_top
from app.database.postgresql import adapter as postgresql_adapter
from app.database.postgresql.views import session as postgresql_session
from app.database.postgresql.views import sql_monitor as postgresql_sql_monitor
from app.database.postgresql.views import top as postgresql_top
from app.views import application as application_views
from app.utils import targets_store


def test_legacy_targets_migrate_to_oracle(tmp_path, monkeypatch):
    database_path = tmp_path / 'legacy-targets.db'
    key_path = tmp_path / 'targets.key'
    monkeypatch.setattr(targets_store, 'DB_FILE', str(database_path))
    monkeypatch.setattr(targets_store, 'KEY_FILE', str(key_path))

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            'CREATE TABLE targets ('
            'name TEXT PRIMARY KEY, host TEXT, port INTEGER, sid TEXT, service TEXT, '
            'encoding TEXT, user TEXT, password_encrypted BLOB, created_at TEXT)'
        )
        connection.execute(
            'INSERT INTO targets (name, host, port, sid, service, encoding, user, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            ('legacy', 'db.example', 1521, 'ORCL', None, 'UTF-8', 'hawk', '2026-01-01'),
        )

    targets_store.init_db()

    migrated = targets_store.list_targets()[0]
    assert migrated['name'] == 'legacy'
    assert migrated['database_type'] == 'oracle'
    assert migrated['database_name'] is None
    assert targets_store.get_targets_dict()['legacy']['database_type'] == 'oracle'


def test_new_targets_default_to_oracle(tmp_path, monkeypatch):
    monkeypatch.setattr(targets_store, 'DB_FILE', str(tmp_path / 'targets.db'))
    monkeypatch.setattr(targets_store, 'KEY_FILE', str(tmp_path / 'targets.key'))

    targets_store.add_target('new', 'db.example', 1521, 'ORCL', None, 'UTF-8', 'hawk', 'secret')

    assert targets_store.list_targets()[0]['database_type'] == 'oracle'


def test_targets_are_grouped_by_database_type_and_name():
    targets = {
        'z-postgres': {'database_type': 'postgresql'},
        'b-oracle': {'database_type': 'oracle'},
        'a-oracle': {'database_type': 'oracle'},
    }

    groups = targets_store.group_targets_by_database(targets)

    assert [label for label, _ in groups] == ['Oracle', 'PostgreSQL']
    assert [[name for name, _ in group] for _, group in groups] == [
        ['a-oracle', 'b-oracle'],
        ['z-postgres'],
    ]


def test_welcome_and_database_selector_group_targets_by_database(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'z-postgres': {'database_type': 'postgresql'},
        'b-oracle': {'database_type': 'oracle'},
        'a-oracle': {'database_type': 'oracle'},
    })
    monkeypatch.setitem(app.config, 'USERS', {'tester': ('', [])})
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/')

    assert response.status_code == 200
    body = response.data.decode()
    assert body.index('<optgroup label="Oracle">') < body.index('<optgroup label="PostgreSQL">')
    assert body.index('a-oracle') < body.index('b-oracle') < body.index('z-postgres')
    assert '<h4>Oracle</h4>' in body
    assert '<h4>PostgreSQL</h4>' in body


def test_oracle_targets_resolve_to_oracle_adapter(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'oracle-target': {'database_type': 'oracle'},
    })

    assert get_adapter('oracle-target').__name__ == 'app.database.oracle.adapter'


def test_unknown_database_type_is_not_assumed_to_be_oracle(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'future-target': {'database_type': 'db2'},
    })

    with pytest.raises(ValueError, match='Unsupported database type: db2'):
        get_adapter('future-target')


def test_postgresql_targets_resolve_to_postgresql_adapter(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })

    assert get_adapter('postgres-target') is postgresql_adapter


def test_registration_validates_selected_postgresql(monkeypatch):
    pg_connection = MagicMock()
    monkeypatch.setattr(registration.psycopg, 'connect', MagicMock(return_value=pg_connection))

    registration.validate_database_connection('postgresql', {
        'host': 'db.example',
        'port': 5432,
        'database_name': 'hawk',
        'user': 'hawk',
        'password': 'secret',
    })

    registration.psycopg.connect.assert_called_once()
    pg_connection.__enter__.assert_called_once()


def test_registration_validates_selected_oracle(monkeypatch):
    oracle_connection = MagicMock()
    connect = MagicMock(return_value=oracle_connection)
    monkeypatch.setattr(registration.oracledb, 'connect', connect)

    registration.validate_database_connection('oracle', {
        'host': 'db.example',
        'port': 1521,
        'sid': 'ORCL',
        'user': 'hawk',
        'password': 'secret',
    })

    connect.assert_called_once()
    oracle_connection.close.assert_called_once()


def test_registration_requires_selected_database_options():
    with pytest.raises(registration.DatabaseConnectionError, match='database name is required'):
        registration.validate_database_connection('postgresql', {'database_name': ''})
    with pytest.raises(registration.DatabaseConnectionError, match='service name or SID is required'):
        registration.validate_database_connection('oracle', {'service': '', 'sid': ''})


def test_registration_rejects_unsupported_database_type():
    with pytest.raises(registration.DatabaseConnectionError, match='Unsupported database type'):
        registration.validate_database_connection('db2', {})


def test_postgresql_parameter_conversion_preserves_casts_and_order():
    statement, parameters = postgresql_adapter._convert_parameters(
        "select :value::integer, ':untouched', :name",
        {'value': 42, 'name': 'HawkEye'},
    )

    assert statement == "select %s::integer, ':untouched', %s"
    assert parameters == (42, 'HawkEye')


def test_postgresql_parameter_conversion_preserves_escaped_like_wildcards():
    statement, parameters = postgresql_adapter._convert_parameters(
        "select 1 where name ilike '%%' || :name || '%%'",
        {'name': 'hawk'},
    )

    assert statement == "select 1 where name ilike '%%' || %s || '%%'"
    assert parameters == ('hawk',)


def test_postgresql_execute_uses_pool_and_fetch_mode(monkeypatch):
    class Cursor:
        def __init__(self):
            self.statement = None
            self.parameters = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, statement, parameters):
            self.statement = statement
            self.parameters = parameters

        def fetchone(self):
            return ('hawk',)

    class Connection:
        def __init__(self):
            self.result_cursor = Cursor()
            self.committed = False

        def cursor(self):
            return self.result_cursor

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def commit(self):
            self.committed = True

    class Pool:
        def __init__(self):
            self.connection_instance = Connection()

        def connection(self):
            return self.connection_instance

    pool = Pool()
    monkeypatch.setattr(postgresql_adapter, '_get_pool', lambda target: pool)

    with app.test_request_context('/postgres-target'):
        result = postgresql_adapter.execute(
            'postgres-target',
            'select :username',
            {'username': 'hawk'},
            fetch_mode='one',
            user_context=False,
        )

    assert result == ('hawk',)
    assert pool.connection_instance.result_cursor.statement == 'select %s'
    assert pool.connection_instance.result_cursor.parameters == ('hawk',)
    assert not pool.connection_instance.committed


def test_oracle_routes_and_templates_are_registered():
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}

    assert {'get_target', 'get_awr_report', 'get_sql_monitor', 'search'} <= endpoints
    assert app.jinja_env.get_template('awr.html').name == 'awr.html'
    assert app.jinja_env.get_template('sql_monitor.html').name == 'sql_monitor.html'


def test_tuning_advisor_report_can_be_exported_as_text(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'oracle-target': {'database_type': 'oracle'},
    })
    monkeypatch.setattr(oracle_top, 'tuning_task_is_successful', lambda *args: True)
    monkeypatch.setattr(
        oracle_top,
        'execute',
        lambda *args, **kwargs: 'Tuning report contents\nRecommendations',
    )
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get(
        '/oracle-target/tuning_advisor/report'
        '?owner=SYS&task_name=SQL_TUNING_TASK&format=txt'
    )

    assert response.status_code == 200
    assert response.mimetype == 'text/plain'
    assert response.headers['Content-Disposition'] == (
        'attachment; filename=SQL_TUNING_TASK.txt'
    )
    assert response.get_data(as_text=True) == 'Tuning report contents\nRecommendations'


def test_tuning_advisor_report_shows_text_export_link(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'oracle-target': {'database_type': 'oracle'},
    })
    monkeypatch.setattr(oracle_top, 'tuning_task_is_successful', lambda *args: True)
    monkeypatch.setattr(oracle_top, 'execute', lambda *args, **kwargs: 'Advisor report')
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get(
        '/oracle-target/tuning_advisor/report?owner=SYS&task_name=SQL_TUNING_TASK'
    )

    assert response.status_code == 200
    assert b'Export .txt' in response.data
    assert b'format=txt' in response.data


def test_postgresql_target_landing_uses_postgresql_summary(monkeypatch):
    assert app.jinja_env.get_template('postgresql/index.html').name == 'postgresql/index.html'
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['tester'])
    monkeypatch.setitem(app.config, 'USERS', {'tester': ('', [])})
    monkeypatch.setattr(postgresql_adapter, 'get_database_info', lambda target: {
        'database_name': 'hawk',
        'host_name': 'postgres-host',
        'connected_as': 'hawk',
        'version': 'PostgreSQL test',
        'startup_time': None,
    })
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/postgres-target')

    assert response.status_code == 200
    assert b'Database name' in response.data
    assert b'PostgreSQL test' in response.data
    assert b'Host name' in response.data
    assert b'Startup time' in response.data
    assert b'Connected as' in response.data
    assert b'Oracle Tuning Advisor' not in response.data
    assert b'Session Monitor' in response.data
    assert b'href="/postgres-target/session_monitor"' in response.data
    assert b'SQL Monitor' in response.data
    assert b'href="/postgres-target/sql_monitor"' in response.data
    assert b'/adm?return_to=%2Fpostgres-target%3F' in response.data


def test_administration_sidebar_hides_database_navigation_and_returns_to_origin(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setitem(app.config, 'USERS', {'admin': ('', [])})
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['admin'])
    monkeypatch.setattr(application_views, 'list_targets', lambda: [])
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'admin'

    entry_response = client.get(
        '/adm?return_to=%2Fpostgres-target%2Fsession_monitor%3Fstatus%3DACTIVE'
    )
    admin_response = client.get(entry_response.headers['Location'])

    assert entry_response.status_code == 302
    assert admin_response.status_code == 200
    assert b'Workload' not in admin_response.data
    assert b'Back to previous page' in admin_response.data
    assert b'href="/postgres-target/session_monitor?status=ACTIVE"' in admin_response.data
    assert b'href="/adm/targets"' in admin_response.data
    assert b'href="/adm/users"' in admin_response.data


def test_administration_ignores_external_return_url(monkeypatch):
    monkeypatch.setitem(app.config, 'USERS', {'admin': ('', [])})
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['admin'])
    monkeypatch.setattr(application_views, 'list_targets', lambda: [])
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'admin'

    entry_response = client.get('/adm?return_to=https%3A%2F%2Fexample.com')
    admin_response = client.get(entry_response.headers['Location'])

    assert b'href="/"' in admin_response.data
    assert b'href="https://example.com"' not in admin_response.data


def test_homepage_sidebar_lists_targets_grouped_by_database(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'pg-one': {'database_type': 'postgresql'},
        'ora-two': {'database_type': 'oracle'},
        'ora-one': {'database_type': 'oracle'},
    })
    monkeypatch.setitem(app.config, 'USERS', {'tester': ('', [])})
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/')
    body = response.get_data(as_text=True)
    sidebar = body.split('<div class="flex-menu">', 1)[1].split(
        '<div class="flex-content">', 1
    )[0]

    assert response.status_code == 200
    assert 'Oracle' in sidebar
    assert 'PostgreSQL' in sidebar
    assert 'href="/ora-one"' in sidebar
    assert 'href="/ora-two"' in sidebar
    assert 'href="/pg-one"' in sidebar
    assert sidebar.index('Oracle') < sidebar.index('ora-one') < sidebar.index('ora-two')
    assert sidebar.index('PostgreSQL') < sidebar.index('pg-one')
    assert 'Workload' not in sidebar


def test_postgresql_target_blocks_oracle_only_routes(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/postgres-target/tuning_advisor')

    assert response.status_code == 501


def test_postgresql_sql_monitor_renders_and_fetches_active_queries(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    execute = MagicMock(return_value=[
        (123, 'query-hash', 'select * from accounts', 'hawk', 'psql',
         'active', 14, 'Lock: transactionid', '127.0.0.1'),
    ])
    monkeypatch.setattr(postgresql_sql_monitor, 'execute', execute)
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    page_response = client.get('/postgres-target/sql_monitor')
    data_response = client.get('/postgres-target/sql_monitor/data')

    assert page_response.status_code == 200
    assert b'SQL Monitor' in page_response.data
    assert b'/postgres-target/sql_monitor/data' in page_response.data
    assert b'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' in page_response.data
    assert b'.refresh-btn:disabled .refresh-icon' in page_response.data
    assert data_response.status_code == 200
    assert data_response.get_json() == [{
        'pid': 123,
        'query_hash': 'query-hash',
        'query_text': 'select * from accounts',
        'username': 'hawk',
        'application': 'psql',
        'state': 'active',
        'elapsed_seconds': 14,
        'wait_event': 'Lock: transactionid',
        'client_addr': '127.0.0.1',
    }]
    assert 'pg_stat_activity' in execute.call_args.args[1]


def test_postgresql_top_activity_page_uses_postgresql_activity_data(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })

    def execute(target, statement, parameters=None, fetch_mode='many', user_context=True):
        if 'from session_counts s' in statement:
            assert parameters == {'user_name': 'hawk', 'query_text': 'select'}
            return (8, 3, 4, 11008, 100, 20, 200, 300, 40, 4000, 5000, 60, 700, 800)
        if 'md5(query)' in statement:
            assert parameters == {'user_name': 'hawk', 'query_text': 'select'}
            return [('query-hash', 2)]
        if 'coalesce(wait_event_type ||' in statement:
            assert parameters == {'user_name': 'hawk', 'query_text': 'select'}
            return [('Lock: transactionid', 1)]
        if 'select pid, datname' in statement:
            assert parameters == {'user_name': 'hawk', 'query_text': 'select'}
            return [(123, 'hawk', 'hawk', 'psql', '127.0.0.1', 'active',
                     'Lock', 'transactionid', 12, 'select * from accounts')]
        raise AssertionError(f'Unexpected query: {statement}')

    monkeypatch.setattr(postgresql_top, 'execute', execute)
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/postgres-target/top?user_name=hawk&query_text=select')

    assert response.status_code == 200
    assert b'sessions(max): 8, sessions(limit): 11008;' in response.data
    assert b'Database sessions' in response.data
    assert b'Transactions per second' in response.data
    assert b'Tuples in per second' in response.data
    assert b'Tuples out per second' in response.data
    assert b'Block I' in response.data
    assert b'Query hash' in response.data
    assert b'query-hash' in response.data
    assert b'class="activity-fetch-status is-success"' in response.data
    assert b'Snapshot loaded' in response.data
    assert b'activity-chart-status-title' in response.data
    assert b'type="submit" value="Filter"' in response.data
    assert b'id="activity-polling-interval"' in response.data
    assert b'value="2"' in response.data
    assert b'min="1"' in response.data
    assert b'max="3600"' in response.data
    assert b'step="1"' in response.data
    assert b'id="activity-chart-fetch"' not in response.data
    assert b'modeBarButtonsToRemove' in response.data
    assert b'Updates every 2 seconds.' in response.data
    assert b'let pollingIntervalSeconds = 2;' in response.data
    assert b'window.setInterval(fetchActivity, pollingIntervalSeconds * 1000)' in response.data
    assert b'window.clearInterval(pollingTimer)' in response.data
    assert b'pollingIntervalInput.addEventListener(\'change\', updatePollingInterval)' in response.data
    assert b'Enter a whole number from 1 to 3600.' in response.data
    assert b'    fetchActivity();' in response.data
    assert response.data.count(b'id="postgres-top-activity-chart"') == 1
    assert b'Top Wait Events' in response.data
    assert b'<th>Event</th><th>Samples</th>' in response.data
    assert b'Active SQL' in response.data
    assert b'transactionid' in response.data
    assert b'select * from accounts' in response.data


def test_postgresql_activity_chart_uses_oracle_chart_layout():
    chart = postgresql_top._activity_chart()

    assert chart.layout.height == 620
    assert chart.layout.paper_bgcolor == 'white'
    assert chart.layout.plot_bgcolor == 'white'
    assert chart.layout.legend.orientation == 'h'
    assert chart.layout.legend.y == 1.02
    assert chart.layout.legend.x == 0.5
    assert chart.layout.legend.entrywidth == 78
    assert chart.layout.legend.entrywidthmode == 'pixels'
    assert chart.layout.margin.t == 88
    assert chart.layout.margin.b == 55
    assert chart.layout.xaxis.tickformat == '%H:%M\n%d.%m'
    assert len(chart.data) == 13
    assert [trace.name for trace in chart.data] == [
        'Total', 'Active', 'Idle',
        'Transactions', 'Commits', 'Rollbacks',
        'Inserts', 'Updates', 'Deletes',
        'Fetched', 'Returned', 'Reads', 'Hits',
    ]
    assert [annotation.text for annotation in chart.layout.annotations] == [
        'Database sessions',
        'Transactions per second',
        'Tuples in per second',
        'Tuples out per second',
        'Block I/O per second',
    ]
    assert [trace.xaxis for trace in chart.data] == [
        'x', 'x', 'x', 'x2', 'x2', 'x2', 'x3', 'x3', 'x3', 'x4', 'x4', 'x5', 'x5',
    ]
    assert [trace.line.color for trace in chart.data] == [
        '#004AE7', '#00CC00', '#9F9371',
        '#5C440B', '#E46800', '#8B1A00',
        '#717354', '#C02800', '#C2B79B',
        '#004AE7', '#F06EAA',
        '#0094E7', '#00CC00',
    ]


def test_postgresql_activity_chart_renders_initial_sample():
    sample = {
        'timestamp': 1761492000.0,
        'total_sessions': 12,
        'active_sessions': 4,
        'idle_sessions': 8,
        'session_limit': 100,
        'transactions_per_second': 0.25,
        'commits_per_second': 0.2,
        'rollbacks_per_second': 0.05,
        'inserts_per_second': 1.0,
        'updates_per_second': 2.0,
        'deletes_per_second': 0.0,
        'fetched_per_second': 4.0,
        'returned_per_second': 5.0,
        'reads_per_second': 0.5,
        'hits_per_second': 8.0,
    }

    chart = postgresql_top._activity_chart(sample)

    assert chart.data[0].y == (12,)
    assert chart.data[3].y == (0.25,)
    assert chart.data[9].y == (4.0,)
    assert chart.data[12].y == (8.0,)
    assert chart.layout.title.text == 'sessions(max): 12, sessions(limit): 100;'


def test_postgresql_activity_metrics_endpoint_returns_stat_counters(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setattr(
        postgresql_top,
        'execute',
        lambda *args, **kwargs: (
            12, 4, 7, 11008, 100, 3, 20, 30, 5, 400, 500, 60, 700, Decimal('800.25'),
        ),
    )
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/postgres-target/top/activity_data')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_sessions'] == 12
    assert payload['active_sessions'] == 4
    assert payload['idle_sessions'] == 7
    assert payload['session_limit'] == 11008
    assert payload['commits'] == 100
    assert payload['rollbacks'] == 3
    assert payload['inserts'] == 20
    assert payload['updates'] == 30
    assert payload['deletes'] == 5
    assert payload['fetched'] == 400
    assert payload['returned'] == 500
    assert payload['reads'] == 60
    assert payload['hits'] == 700
    assert payload['transactions_per_second'] >= 0
    assert isinstance(payload['stats_reset'], float)
    assert isinstance(payload['timestamp'], float)


def test_postgresql_activity_metrics_escapes_literal_like_wildcard():
    statement, parameters = postgresql_adapter._convert_parameters(
        "select 1 where wait_event like 'WAL%%' and usename = :user_name",
        {'user_name': 'hawk'},
    )

    assert "wait_event like 'WAL%%'" in statement
    assert parameters == ('hawk',)


def test_postgresql_activity_metrics_endpoint_is_not_available_for_oracle(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'oracle-target': {'database_type': 'oracle'},
    })
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/oracle-target/top/activity_data')

    assert response.status_code == 404


def test_postgresql_session_monitor_filters_and_renders_sessions(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })

    def execute(target, statement, parameters=None, fetch_mode='many', user_context=True):
        assert 'pg_stat_activity' in statement
        assert parameters == {'status': 'idle'}
        return [(123, 'query-hash', 'hawk', 'alice', 'idle', '127.0.0.1',
                 'psql', None, None, 'Client', 'ClientRead', 4, 'select 1')]

    monkeypatch.setattr(postgresql_session, 'execute', execute)
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'tester'

    response = client.get('/postgres-target/session_monitor?status=IDLE')

    assert response.status_code == 200
    assert b'Session Monitor' in response.data
    assert b'IDLE' in response.data
    assert b'query-hash' in response.data
    assert b'ClientRead' in response.data
    assert b'select 1' in response.data
    assert b'Terminate' not in response.data


def test_postgresql_session_termination_requires_admin(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['admin'])
    execute = MagicMock()
    monkeypatch.setattr(postgresql_session, 'execute', execute)
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'viewer'

    response = client.post('/postgres-target/postgresql/terminate_session', data={'pid': '123'})

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/postgres-target/session_monitor')
    execute.assert_not_called()


def test_postgresql_admin_can_terminate_valid_client_session(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['admin'])
    monkeypatch.setitem(app.config, 'USERS', {'admin': ('', [])})
    execute = MagicMock(return_value=(True,))
    monkeypatch.setattr(postgresql_session, 'execute', execute)
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'admin'

    response = client.post('/postgres-target/postgresql/terminate_session', data={'pid': '123'})

    assert response.status_code == 302
    execute.assert_called_once()
    assert 'pg_terminate_backend(pid)' in execute.call_args.args[1]
    assert execute.call_args.kwargs['fetch_mode'] == 'one'
    assert execute.call_args.args[2] == {'pid': 123}


def test_postgresql_termination_can_return_to_sql_monitor(monkeypatch):
    monkeypatch.setitem(app.config, 'TARGETS', {
        'postgres-target': {'database_type': 'postgresql'},
    })
    monkeypatch.setitem(app.config, 'ADMIN_GROUP', ['admin'])
    monkeypatch.setitem(app.config, 'USERS', {'admin': ('', [])})
    monkeypatch.setattr(postgresql_session, 'execute', MagicMock(return_value=(True,)))
    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session['user_name'] = 'admin'

    response = client.post(
        '/postgres-target/postgresql/terminate_session',
        data={'pid': '123', 'return_to': 'sql_monitor'},
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/postgres-target/sql_monitor')
