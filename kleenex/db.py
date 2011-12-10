import time

from operator import or_
from sqlalchemy import create_engine, Table, MetaData, Integer, String, \
  Column, UniqueConstraint, ForeignKey
from sqlalchemy.sql import select

metadata = MetaData()
Tests = Table('tests', metadata,
    Column('id', Integer, primary_key=True),
    Column('test', String, unique=True),
    Column('revision', String, index=True),
)
Coverage = Table('coverage', metadata,
    Column('id', Integer, primary_key=True),
    Column('filename', String),
    Column('lineno', Integer),
    Column('test_id', Integer, ForeignKey('tests.id'), index=True),
    UniqueConstraint('filename', 'lineno', 'test_id'),
)

class TestCoverageDB(object):
    def __init__(self, dsn, logger):
        self.logger = logger
        self.engine = create_engine(dsn)
        self.conn = self._connect_db()

        self._coverage = {}

    def _connect_db(self):
        self.logger.info('Connecting to coverage database..')
        s = time.time()
        conn = self.engine.connect()
        self.logger.info('Connection established to coverage database in %.2fs', time.time() - s)
        return conn

    def _get_test_id(self, test):
        result = self.conn.execute(select([Tests.c.id]).where(Tests.c.test == test)).fetchone()
        return result[0] if result else None

    def upgrade(self):
        metadata.create_all(self.conn, checkfirst=True)

    def begin(self):
        return self.conn.begin()

    def has_seen_test(self, test):
        statement = select([Tests.c.id]).where(Tests.c.test == test).limit(1)
        result = bool(self.conn.execute(statement).fetchall())
        return result

    def has_test_coverage(self, filename):
        if filename not in self._coverage:
            statement = select([Coverage.c.id]).where(Coverage.c.filename == filename).limit(1)
            return bool(self.conn.execute(statement).fetchall())
        return bool(self._coverage[filename])

    def get_test_coverage(self, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
            statement = select([Coverage.c.lineno, Tests.c.test]).where(Coverage.c.filename == filename).where(Coverage.c.lineno.in_(linenos))
            for lineno, test in self.conn.execute(statement).fetchall():
                file_cover.setdefault(lineno, set()).add(test)
        return reduce(or_, (self._coverage[filename].get(l, set()) for l in linenos))

    def clear_test_coverage(self, test):
        # clean up existing tests
        test_id = self._get_test_id(test)

        if not test_id:
            return

        statement = select([Coverage.c.lineno, Tests.c.test], Coverage.c.test_id == test_id)
        for filename, lineno in self.conn.execute(statement).fetchall():
            if filename not in self._coverage:
                continue
            if lineno not in self._coverage[filename]:
                continue
            self._coverage[filename][lineno].discard(test)

        self.conn.execute(Tests.delete().where(Tests.c.test == test))
        self.conn.execute(Coverage.delete().where(Coverage.c.test_id == test_id))

    def set_test_has_coverage(self, test, revision):
        self.conn.execute(Tests.insert().values(test=test, revision=revision))

    def set_test_coverage(self, test, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
        else:
            file_cover = self._coverage[filename]

        test_id = self._get_test_id(test)

        # add new data
        for lineno in linenos:
            file_cover.setdefault(lineno, set()).add(test)
            self.conn.execute(Coverage.insert().values(filename=filename, lineno=lineno, test_id=test_id))