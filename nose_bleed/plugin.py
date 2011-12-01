from __future__ import absolute_import

import cPickle as pickle
import gzip
import logging
import os
import sys
import time
import traceback

from coverage import coverage
from coverage.report import Reporter
from nose.plugins.base import Plugin
from nose_bleed.diff import DiffParser
from subprocess import Popen, PIPE, STDOUT

COVERAGE_DATA_FILE = 'coverage.db.gz'

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
        if os.path.exists(COVERAGE_DATA_FILE):
            self.logger.info("Loading pickled coverage data from %s..", COVERAGE_DATA_FILE)
            s = time.time()
            with gzip.open(COVERAGE_DATA_FILE, 'rb') as fp:
                self.test_coverage = pickle.load(fp)
            self.logger.info("Loaded coverage data in %.2fs", time.time() - s)

        elif self.discover:
            raise ValueError('You cannot use --discover without having done --record-test-coverage first.')
        else:
            self.test_coverage = {}

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

            if filename not in self.test_coverage:
                if self.skip_missing:
                    self.logger.warning('%s has no test coverage recorded', filename)
                    continue
                raise AssertionError("Missing test coverage for %s" % filename)

            for chunk in file['chunks']:
                lineiter = iter(chunk)
                try:
                    while True:
                        line = lineiter.next()
                        lineno = line['old_lineno']
                        if lineno in self.test_coverage[filename]:
                            pending_funcs.update(self.test_coverage[filename][lineno])
                except StopIteration:
                    pass
        self.logger.info("Determined available coverage in %.2fs", time.time() - s)

    def wantMethod(self, method):
        if not self.discover:
            return

        # only works with unittest compatible functions currently
        func_name = '%s:%s.%s' % (method.im_class.__module__, method.im_class.__name__, method.__name__)
        if func_name in self.pending_funcs:
            return True
        return False

    def finalize(self, result):
        self.logger.info("Saving coverage data to %s", COVERAGE_DATA_FILE)
        s = time.time()
        with gzip.open(COVERAGE_DATA_FILE, 'wb') as fp:
            pickle.dump(self.test_coverage, fp, 1)
        self.logger.info("Saved coverage data in %.2fs", time.time() - s)

    def startTest(self, test):
        self.coverage = coverage(include='disqus/*')
        self.coverage.start()

    def stopTest(self, test):
        cov = self.coverage
        cov.stop()

        test_ = test.test
        test_name = '%s:%s.%s' % (test_.__class__.__module__, test_.__class__.__name__,
                                                     test_._testMethodName)

        units = self.test_coverage

        # initialize reporter
        rep = Reporter(cov)

        # process all files
        rep.find_code_units(None, cov.config)

        for cu in rep.code_units:
            try:
                # TODO: this CANT work in all cases, must be a better way
                analysis = rep.coverage._analyze(cu)
                filename = cu.name + '.py'
                if filename not in units:
                    units[filename] = {}
                for lineno in analysis.statements:
                    if lineno not in units[filename]:
                        units[filename][lineno] = set([test_name])
                    else:
                        units[filename][lineno].add(test_name)
            except KeyboardInterrupt:                       # pragma: no cover
                raise
            except:
                traceback.print_exc()

