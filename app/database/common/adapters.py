from importlib import import_module

from app import app


def get_adapter(target):
    target_config = app.config['TARGETS'].get(target)
    if target_config is None:
        raise KeyError(f'Unknown database target: {target}')

    database_type = target_config.get('database_type', 'oracle').lower()
    if database_type not in ('oracle', 'postgresql'):
        raise ValueError(f'Unsupported database type: {database_type}')
    return import_module(f'app.database.{database_type}.adapter')


def cancel_active(request_id):
    from app import active_connections

    connection = active_connections.get(request_id)
    if connection is None:
        return False
    adapter = get_adapter(connection[3])
    return adapter.cancel_active(request_id)


def close_target_pool(target):
    from app import lock, target_pool

    with lock:
        pool = target_pool.pop(target, None)
    if pool is not None:
        pool.close()
