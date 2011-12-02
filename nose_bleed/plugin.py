from __future__ import absolute_import

import logging
import os
import sqlite3
import time
import traceback

from coverage import coverage
from coverage.report import Reporter
from nose.plugins.base import Plugin
from nose_bleed.diff import DiffParser
from operator import or_
from subprocess import Popen, PIPE, STDOUT

COVERAGE_DATA_FILE = 'coverage.db'

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

def upgrade_database(conn):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coverage (
      id INTEGER PRIMARY KEY,
      filename TEXT,
      lineno INTEGER,
      test TEXT,
      UNIQUE (filename, lineno, test)
    )
    """)
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
      coverage_test ON coverage (test)
    """)
    cursor.close()

class TestCoverageDB(object):
    def __init__(self, conn):
        self.conn = conn
        self._coverage = {}

    def has_test_coverage(self, filename):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
            cursor = self.conn.cursor()
            cursor.execute("SELECT lineno, test FROM coverage WHERE filename = ?", [filename])
            for lineno, test in cursor.fetchall():
                file_cover.setdefault(lineno, set()).add(test)
            self.conn.commit()
            cursor.close()
        return bool(self._coverage[filename])

    def get_test_coverage(self, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
            cursor = self.conn.cursor()
            cursor.execute("SELECT lineno, test FROM coverage WHERE filename = ? and lineno IN (%s)" % ', '.join(map(int, linenos)), [filename])
            for lineno, test in cursor.fetchall():
                file_cover.setdefault(lineno, set()).add(test)
            self.conn.commit()
            cursor.close()
        return reduce(or_, (self._coverage[filename].get(l, set()) for l in linenos))

    def clear_test_coverage(self, test):
        cursor = self.conn.cursor()

        # clean up existing tests
        cursor.execute("SELECT filename, lineno FROM coverage WHERE test = ?", [test])
        for filename, lineno in cursor.fetchall():
            if filename not in self._coverage:
                continue
            if lineno not in self._coverage[filename]:
                continue
            self._coverage[filename][lineno].discard(test)

        cursor.execute("DELETE FROM coverage WHERE test = ?", [test])

        self.conn.commit()

        cursor.close()

    def set_test_coverage(self, test, filename, linenos):
        if filename not in self._coverage:
            self._coverage[filename] = file_cover = {}
        else:
            file_cover = self._coverage[filename]

        cursor = self.conn.cursor()

        # add new data
        for lineno in linenos:
            file_cover.setdefault(lineno, set()).add(test)
            cursor.execute("INSERT INTO coverage (filename, lineno, test) VALUES(?, ?, ?)", [filename, lineno, test])

        self.conn.commit()

        cursor.close()

class TestCoveragePlugin(Plugin):
    """
    Monitors tests to discover which tests cover which
    lines of code. Serializes results to ``COVERAGE_DATA_FILE``.

    We find the diff with the parent revision for diff-tests with::

        git diff `git merge-base HEAD origin/master`

    If you run with the --discover flag, it will attempt to discovery
    any tests that are required to run to test the changes in your current
    branch, against those of origin/master.

    """
    def options(self, parser, env):
        parser.add_option("--record-test-coverage",
                          dest="record_test_coverage", action="store_true",
                          default=None)

        parser.add_option("--skip-missing-coverage",
                          dest="skip_missing_coverage", action="store_true",
                          default=None)

        parser.add_option("--discover",
                          dest="discover", action="store_true",
                          default=None)

    def configure(self, options, config):
        self.enabled = (options.record_test_coverage or options.discover)
        self.skip_missing = options.skip_missing_coverage
        self.discover = options.discover
        self.logger = logging.getLogger(__name__)

    def begin(self):
        db_exists = os.path.exists(COVERAGE_DATA_FILE)
        if not db_exists and self.discover:
            raise ValueError('You cannot use --discover without having done --record-test-coverage first.')

        conn = sqlite3.connect(COVERAGE_DATA_FILE)

        upgrade_database(conn)

        self.db = TestCoverageDB(conn)

        if not self.discover:
            return

        # pull in our diff
        # git diff `git merge-base HEAD master`
        proc = Popen('git merge-base HEAD origin/master'.split(), stdout=PIPE, stderr=STDOUT)
        parent = proc.stdout.read().strip()
        proc = Popen(('git diff %s' % parent).split(), stdout=PIPE, stderr=STDOUT)
        diff = proc.stdout.read()

        pending_funcs = self.pending_funcs = set()

        self.logger.info("Parsing diff from parent %s", parent)
        s = time.time()
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

            if not self.db.has_test_coverage(filename):
                if self.skip_missing:
                    self.logger.warning('%s has no test coverage recorded', filename)
                    continue
                raise AssertionError("Missing test coverage for %s" % filename)

            for chunk in file['chunks']:
                linenos = [l['old_lineno'] for l in chunk]
                pending_funcs.update(self.db.get_test_coverage(filename, linenos))

        self.logger.info("Determined available coverage in %.2fs with %d test(s)", time.time() - s, len(pending_funcs))

    def wantMethod(self, method):
        if not self.discover:
            return

        # only works with unittest compatible functions currently
        func_name = '%s:%s.%s' % (method.im_class.__module__, method.im_class.__name__, method.__name__)
        if func_name in self.pending_funcs:
            return True
        return False

    def startTest(self, test):
        self.coverage = coverage(include='disqus/*')
        self.coverage.start()

    def stopTest(self, test):
        cov = self.coverage
        cov.stop()

        test_ = test.test
        test_name = '%s:%s.%s' % (test_.__class__.__module__, test_.__class__.__name__,
                                                     test_._testMethodName)
        # initialize reporter
        rep = Reporter(cov)

        # process all files
        rep.find_code_units(None, cov.config)

        self.db.clear_test_coverage(test_name)

        for cu in rep.code_units:
            try:
                # TODO: this CANT work in all cases, must be a better way
                analysis = rep.coverage._analyze(cu)
                filename = cu.name + '.py'
                self.db.set_test_coverage(test_name, filename, analysis.statements)
            except KeyboardInterrupt:                       # pragma: no cover
                raise
            except:
                traceback.print_exc()

