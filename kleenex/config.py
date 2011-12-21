from ConfigParser import RawConfigParser


class Config(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def read_config(filename, section='kleenex'):
    """
    This looks for [kleenex] in ``filename`` such as the following:

    [kleenex]
    db = sqlite:///coverage.db
    parent = origin/master
    discover = true
    report = true
    report_output = -
    record = true
    skip_missing = true
    max_distance = 4
    test_missing = true
    """
    config = RawConfigParser({
        'db': 'sqlite:///coverage.db',
        'parent': 'origin/master',
        'discover': 'false',
        'report': 'true',
        'report_output': '-',
        'record': 'false',
        'skip_missing': 'true',
        'max_distance': '4',
        'test_missing': 'true',
    }, dict_type=Config)
    config.read(filename)

    if not config.has_section(section):
        return config.defaults()

    return Config({
        'db': config.get(section, 'db'),
        'parent': config.get(section, 'parent'),
        'discover': config.getboolean(section, 'discover'),
        'report': config.getboolean(section, 'report'),
        'report_output': config.get(section, 'report_output'),
        'record': config.getboolean(section, 'record'),
        'skip_missing': config.getboolean(section, 'skip_missing'),
        'max_distance': config.getint(section, 'max_distance'),
        'test_missing': config.getboolean(section, 'test_missing'),
    })
