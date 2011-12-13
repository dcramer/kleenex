import ConfigParser

class Config(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__

def read_config(filename):
    """
    This looks for [kleenex] in ``filename`` such as the following:

    [kleenex]
    db = sqlite:///coverage.db
    parent = origin/master
    discover = true
    report = true
    report_output = sys://stdout
    record = true
    skip_missing = true
    max_distance = 4
    allow_missing = true
    """
    config = ConfigParser.RawConfigParser(allow_no_value=False)
    config.read(filename)

    ns = 'kleenex'

    return Config({
        'db': config.get(ns, 'db') or 'sqlite:///coverage.db',
        'parent': config.get(ns, 'parent') or 'origin/master',
        'discover': config.getboolean(ns, 'discover') or False,
        'report': config.getboolean(ns, 'report') or False,
        'report_output': config.get(ns, 'report_output') or 'sys://stdout',
        'record': config.getboolean(ns, 'record') or False,
        'skip_missing': config.getBoolean(ns, 'skip_missing') or True,
        'max_distance': config.getInt(ns, 'max_distance') or 4,
        'allow_missing': config.getBoolean(ns, 'allow_missing') or True,
    })