import oracledb
import psycopg


class DatabaseConnectionError(ValueError):
    pass


def validate_database_connection(database_type, connection_info):
    if database_type == 'postgresql':
        database_name = connection_info.get('database_name', '').strip()
        if not database_name:
            raise DatabaseConnectionError('PostgreSQL database name is required.')
        try:
            with psycopg.connect(
                host=connection_info['host'],
                port=connection_info.get('port') or 5432,
                dbname=database_name,
                user=connection_info['user'],
                password=connection_info['password'],
                connect_timeout=5,
            ):
                pass
        except psycopg.Error as error:
            raise DatabaseConnectionError(f'PostgreSQL connection failed: {error}') from error
        return

    if database_type == 'oracle':
        service = connection_info.get('service', '').strip()
        sid = connection_info.get('sid', '').strip()
        if not service and not sid:
            raise DatabaseConnectionError('Oracle service name or SID is required.')
        oracle_connection = {
            'host': connection_info['host'],
            'port': connection_info.get('port') or 1521,
            'user': connection_info['user'],
            'password': connection_info['password'],
            'tcp_connect_timeout': 5,
        }
        oracle_connection['service_name' if service else 'sid'] = service or sid
        try:
            connection = oracledb.connect(**oracle_connection)
            connection.close()
        except oracledb.Error as error:
            raise DatabaseConnectionError(f'Oracle connection failed: {error}') from error
        return

    raise DatabaseConnectionError(f'Unsupported database type: {database_type}')
