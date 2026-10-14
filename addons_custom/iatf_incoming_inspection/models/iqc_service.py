"""An in-process capability; booleans supplied by an RPC context are not authority."""
_TOKEN = object()
_CONTEXT = '_iqc_stock_service'


def service(record):
    return record.with_context(**{_CONTEXT: _TOKEN})


def is_service(env):
    return env.context.get(_CONTEXT) is _TOKEN
