from __future__ import absolute_import

import logging
import os
import sys
import time
import traceback

from coverage import coverage
from coverage.report import Reporter
from nose.plugins.base import Plugin
from nose_bleed.diff import DiffParser
from operator import or_
from subprocess import Popen, PIPE, STDOUT
from sqlalchemy import create_engine, Table, MetaData, Integer, String, \
  Column
from sqlalchemy.sql import select

def is_py_script(filename):
    "Returns True if a file is a python executable."
    if filename.endswith(".py") and os.path.exists(filename):
        return True
    elif not os.access(filename, os.X_OK):
        return False
    else:
        try:
            first_line = open(filename, "r").next().strip()
            return "#!" in first_line and "python" in first_line
        except StopIteration:
            return False

metadata = MetaData()
Coverage = Table('coverage', metadata,
    Column('id', Integer, primary_key=True),
    Column('filename', String),
    Column('lineno', Integer),
    Column('test', String, index=True)
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

    def upgrade(self):
        metadata.create_all(self.conn)

    def begin(self):
        return self.conn.begin()

    def has_seen_test(self, test):
        statement = select([Coverage.c.id], Coverage.c.test == test, limit=1)
        result = bool(self.conn.execute(statement).fetchall())
        return result

    def has_test_coverage(self, filename):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
            statement = select([Coverage.c.lineno, Coverage.c.test], Coverage.c.filename == filename)
            for lineno, test in self.conn.execute(statement).fetchall():
                file_cover.setdefault(lineno, set()).add(test)
            self.commit()
        return bool(self._coverage[filename])

    def get_test_coverage(self, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
            statement = select([Coverage.c.lineno, Coverage.c.test], Coverage.c.filename == filename, Coverage.c.lineno.in_(linenos))
            for lineno, test in self.conn.execute(statement).fetchall():
                file_cover.setdefault(lineno, set()).add(test)
        return reduce(or_, (self._coverage[filename].get(l, set()) for l in linenos))

    def clear_test_coverage(self, test):
        # clean up existing tests
        statement = select([Coverage.c.lineno, Coverage.c.test], Coverage.c.test==test)
        for filename, lineno in self.conn.execute(statement).fetchall():
            if filename not in self._coverage:
                continue
            if lineno not in self._coverage[filename]:
                continue
            self._coverage[filename][lineno].discard(test)

        self.conn.execute(Coverage.delete().where(Coverage.c.test == test))

    def set_test_coverage(self, test, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
        else:
            file_cover = self._coverage[filename]

        # add new data
        for lineno in linenos:
            file_cover.setdefault(lineno, set()).add(test)
            self.conn.execute(Coverage.insert().values(filename=filename, lineno=lineno, test=test))

class TestCoveragePlugin(Plugin):
    """
    Monitors tests to discover which tests cover which
    lines of code.

    We find the diff with the parent revision for diff-tests with::

        git diff origin/master

    If you run with the --discover flag, it will attempt to discovery
    any tests that are required to run to test the changes in your current
    branch, against those of origin/master.

    """
    score = 0

    def _get_name_from_test(self, test):
        test_method_name = test._testMethodName

        # We need to determine the *actual* test path (as thats what nose gives us in wantMethod)
        # for example, maybe a test was imported in foo.bar.tests, but originated as foo.bar.something.MyTest
        # in this case, we'd need to identify that its *actually* foo.bar.something.MyTest to record the
        # proper coverage
        test_ = getattr(sys.modules[test.__module__], test.__class__.__name__)

        test_name = '%s:%s.%s' % (test_.__module__, test_.__name__,
                                                     test_method_name)

        return test_name

    def options(self, parser, env):
        parser.add_option('--coverage-parent',
                          dest="coverage_parent",
                          default="origin/master")

        parser.add_option("--record-test-coverage",
                          dest="record_test_coverage", action="store_true",
                          default=False)

        parser.add_option("--no-record-test-coverage",
                          dest="record_test_coverage", action="store_false",
                          default=False)

        parser.add_option("--skip-missing-coverage",
                          dest="skip_missing_coverage", action="store_true",
                          default=None)

        parser.add_option("--no-skip-missing-coverage",
                          dest="skip_missing_coverage", action="store_false",
                          default=None)

        parser.add_option("--no-coverage-discovery",
                          dest="discover", action="store_false",
                          default=True)

        parser.add_option("--coverage-dsn",
                          dest="coverage_dsn",
                          default='sqlite:///coverage.db')

    def configure(self, options, config):
        self.enabled = (options.record_test_coverage or options.discover)
        self.skip_missing = options.skip_missing_coverage
        self.record = options.record_test_coverage
        self.discover = options.discover
        self.logger = logging.getLogger(__name__)
        self.dsn = options.coverage_dsn
        self.parent = options.coverage_parent
        self.pending_funcs = set()

    def begin(self):
        # XXX: this is pretty hacky
        self.db = TestCoverageDB(self.dsn, self.logger)
        if self.record:
            self.db.upgrade()

        if not self.discover:
            return

        s = time.time()
        self.logger.info("Parsing diff from parent %s", self.parent)
        # pull in our diff
        # git diff `git merge-base HEAD master`
        proc = Popen(['git', 'diff', self.parent], stdout=PIPE, stderr=STDOUT)
        diff = proc.stdout.read()

        pending_funcs = self.pending_funcs

        parser = DiffParser(diff)
        files = list(parser.parse())
        self.logger.info("Parsed diff in %.2fs", time.time() - s)

        self.logger.info("Finding coverage for %d file(s)", len(files))
        s = time.time()
        for file in files:
            if file['is_header']:
                continue

            if file['old_filename'] == '/dev/null':
                continue

            filename = file['old_filename']
            if not filename.startswith('a/'):
                continue # ??

            filename = filename[2:]

            # Ignore non python files
            if not is_py_script(filename):
                continue

            # TODO: for this to be useful we need to eliminate tests
            if not self.db.has_test_coverage(filename):
                if self.skip_missing:
                    self.logger.warning('%s has no test coverage recorded', filename)
                    continue
                raise AssertionError("Missing test coverage for %s" % filename)

            for chunk in file['chunks']:
                linenos = [l['old_lineno'] for l in chunk]
                for test in self.db.get_test_coverage(filename, linenos):
                    pending_funcs.add(test)

        self.logger.info("Determined available coverage in %.2fs with %d test(s)", time.time() - s, len(pending_funcs))

    def wantMethod(self, method):
        if not self.discover:
            return

        # only works with unittest compatible functions currently
        test_name = '%s:%s.%s' % (method.im_class.__module__, method.im_class.__name__, method.__name__)

        # test has coverage for diff
        if test_name in self.pending_funcs:
            return True

        # test has no coverage recorded, defer to other plugins
        elif not self.db.has_seen_test(test_name):
            self.pending_funcs.add(test_name)
            self.logger.info("Allowing test due to missing coverage report: %s", test_name)
            return None

        return False

    def startTest(self, test):
        if not self.record:
            return

        self.coverage = coverage(include='disqus/*')
        self.coverage.start()

    def stopTest(self, test):
        if not self.record:
            return

        cov = self.coverage
        cov.stop()

        test_ = test.test
        test_name = self._get_name_from_test(test_)

        # this must have been imported under a different name
        if self.discover and test_name not in self.pending_funcs:
            self.logger.warning("Unable to determine origin for test: %s", test_name)
            return

        # initialize reporter
        rep = Reporter(cov)

        # process all files
        rep.find_code_units(None, cov.config)

        # The rest of this is all run within a single transaction
        trans = self.db.begin()

        self.db.clear_test_coverage(test_name)

        for cu in rep.code_units:
            if sys.modules[test_.__module__].__file__ == cu.filename:
                continue
            filename = cu.name + '.py'
            try:
                # TODO: this CANT work in all cases, must be a better way
                analysis = rep.coverage._analyze(cu)
                self.db.set_test_coverage(test_name, filename, analysis.statements)
            except KeyboardInterrupt:                       # pragma: no cover
                raise
            except:
                traceback.print_exc()

        trans.commit()

