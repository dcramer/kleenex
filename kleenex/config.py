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
    report_output =
    record = true
    skip_missing = true
    max_distance = 4
    test_missing = true
    """
    config = ConfigParser.RawConfigParser({
        'db': 'sqlite:///coverage.db',
        'parent': 'origin/master',
        'discover': 'false',
        'report': 'true',
        'report_output': '',
        'record': 'false',
        'skip_missing': 'true',
        'max_distance': '4',
        'test_missing': 'true',
    }, dict_type=Config, allow_no_value=False)
    config.read(filename)

    ns = 'kleenex'

    if not config.has_section(ns):
        return config.defaults()

    return Config({
        'db': config.get(ns, 'db'),
        'parent': config.get(ns, 'parent'),
        'discover': config.getboolean(ns, 'discover'),
        'report': config.getboolean(ns, 'report'),
        'report_output': config.get(ns, 'report_output'),
        'record': config.getboolean(ns, 'record'),
        'skip_missing': config.getboolean(ns, 'skip_missing'),
        'max_distance': config.getint(ns, 'max_distance'),
        'test_missing': config.getboolean(ns, 'test_missing'),
    })