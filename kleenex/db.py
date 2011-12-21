"""
kleenex.db
~~~~~~~~~~

:copyright: 2011 DISQUS.:license: BSD
"""

import time

from collections import defaultdict
from sqlalchemy import create_engine, Table, MetaData, Integer, String, \
  Column, UniqueConstraint, ForeignKey, DateTime
from sqlalchemy.sql import select

metadata = MetaData()
Revisions = Table('revisions', metadata,
    Column('id', Integer, primary_key=True),
    Column('revision', String, unique=True),
    Column('commit_date', DateTime),
)
Tests = Table('tests', metadata,
    Column('id', Integer, primary_key=True),
    Column('test', String, unique=True),
    Column('revision_id', Integer, ForeignKey('revisions.id'), index=True),
)
Coverage = Table('coverage', metadata,
    Column('id', Integer, primary_key=True),
    Column('filename', String),
    Column('lineno', Integer),
    Column('distance', Integer),
    Column('test_id', Integer, ForeignKey('tests.id'), index=True),
    Column('revision_id', Integer, ForeignKey('revisions.id'), index=True),
    UniqueConstraint('filename', 'lineno', 'test_id'),
)


class CoverageDB(object):
    def __init__(self, dsn, logger):
        self.logger = logger
        self.engine = create_engine(dsn)
        self.conn = self._connect_db()

    def _connect_db(self):
        self.logger.info('Connecting to coverage database..')
        s = time.time()
        conn = self.engine.connect()
        self.logger.info('Connection established to coverage database in %.2fs', time.time() - s)
        return conn

    def _execute(self, statement, params=None):
        return self.conn.execute(statement, params or [])

    def upgrade(self):
        metadata.create_all(self.conn, checkfirst=True)

    def begin(self):
        return self.conn.begin()

    def add_revision(self, revision, commit_date):
        statement = select([Revisions.c.id]).where(Revisions.c.revision == revision)
        result = self._execute(statement).fetchall()

        if result:
            return result[0][0]

        result = self._execute(Revisions.insert().values(revision=revision, commit_date=commit_date))

        return result.inserted_primary_key[0]

    def remove_revision(self, revision_id):
        "Removes all data related to a revision (run in a transaction)."
        trans = self.begin()
        self._execute(Coverage.delete().where(Tests.c.revision_id == revision_id))
        self._execute(Tests.delete().where(Tests.c.revision_id == revision_id))
        self._execute(Revisions.delete().where(Revisions.c.revision_id == revision_id))
        trans.commit()

    def trim_revisions(self, num_to_keep):
        statement = select([Revisions.c.id]).order_by(Revisions.c.commit_date.desc())\
          .offset(num_to_keep)
        result = self._execute(statement).fetchall()

        if not result:
            return 0

        num_trimmed = 0
        for revision in result:
            num_trimmed += 1
            self.remove_revision(revision[0])

        return num_trimmed

    def get_revision_id(self, revision):
        statement = select([Revisions.c.id]).where(Revisions.c.revision == revision).limit(1)
        result = self._execute(statement).fetchall()

        if not result:
            raise ValueError(revision)

        return result[0][0]

    def add_test(self, revision_id, test):
        result = self._execute(Tests.insert().values(test=test, revision_id=revision_id))
        return result.inserted_primary_key[0]

    def remove_test(self, revision_id, test):
        # clean up existing tests
        test_id = self.get_test_id(test)

        if not test_id:
            return

        self.remove_coverage(revision_id, test_id)
        self._execute(Tests.delete().where(Tests.c.test == test))

    def has_test(self, revision_id, test):
        statement = select([Tests.c.id]).where(Tests.c.test == test)\
          .where(Tests.c.revision_id == revision_id).limit(1)
        result = bool(self._execute(statement).fetchall())

        return result

    def get_test_id(self, test):
        result = self._execute(select([Tests.c.id]).where(Tests.c.test == test)).fetchone()
        return result[0] if result else None

    def add_coverage(self, revision_id, test_id, filename, linenos):
        """
        linenos should be a dictionary:
            {lineno: distance}
        """
        # add new data
        ins = Coverage.insert()
        self._execute(ins, [{
            'filename': filename,
            'lineno': lineno,
            'distance': distance,
            'test_id': test_id,
            'revision_id': revision_id,
        } for lineno, distance in linenos.iteritems()])

    def remove_coverage(self, revision_id, test_id):
        self._execute(Coverage.delete().where(Coverage.c.test_id == test_id))

    def has_coverage(self, revision_id, filename):
        statement = select([Coverage.c.id])\
          .where(Coverage.c.filename == filename)\
          .where(Coverage.c.revision_id == revision_id)\
          .limit(1)

        return bool(self._execute(statement).fetchall())

    def get_coverage(self, revision_id, filename, linenos):
        statement = select([Tests.c.test])\
          .where(Tests.c.id == Coverage.c.test_id)\
          .where(Coverage.c.filename == filename)\
          .where(Coverage.c.revision_id == revision_id)\
          .where(Coverage.c.lineno.in_(linenos))\
          .distinct()

        return [r[0] for r in self._execute(statement).fetchall()]
