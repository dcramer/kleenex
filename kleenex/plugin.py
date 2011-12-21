"""
kleenex.plugin
~~~~~~~~~~~~~~

:copyright: 2011 DISQUS.
:license: BSD
"""

from __future__ import absolute_import

import datetime
import logging
import os
import simplejson
import sys
import time

from coverage import coverage
from coverage.report import Reporter
from collections import defaultdict
from nose.plugins.base import Plugin
from subprocess import Popen, PIPE, STDOUT

from kleenex.config import read_config
from kleenex.db import CoverageDB
from kleenex.diff import DiffParser
from kleenex.tracer import ExtendedTracer
from kleenex.utils import is_py_script


class TestCoveragePlugin(Plugin):
    """
    Monitors tests to discover which tests cover which
    lines of code.

    We find the diff with the parent revision for diff-tests with::

        git diff origin/master

    If you run with the discover flag, it will attempt to discovery
    any tests that are required to run to test the changes in your current
    branch, against those of origin/master.

    """
    score = 0
    name = 'kleenex'

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

    def _setup_coverage(self):
        instance = coverage(include=os.path.join(os.getcwd(), '*'))
        instance.collector._trace_class = ExtendedTracer
        instance.use_cache(False)

        return instance

    def options(self, parser, env):
        Plugin.options(self, parser, env)
        parser.add_option("--kleenex-config", dest="kleenex_config", default="setup.cfg")
        parser.add_option("--kleenex-config-section", dest="kleenex_config_section", default="kleenex")

    def configure(self, options, config):
        Plugin.configure(self, options, config)
        if not self.enabled:
            return

        config = read_config(options.kleenex_config, options.kleenex_config_section)

        self.config = config

        assert not (self.config.discover and self.config.record), "You cannot use both `record` and `discover` options."

        self.logger = logging.getLogger(__name__)

        self.pending_funcs = set()
        # diff is a mapping of filename->[linenos]
        self.diff_data = defaultdict(set)
        # cov is a mapping of filename->[linenos]
        self.cov_data = defaultdict(set)

        report_output = config.report_output
        if not report_output or report_output == '-':
            self.report_file = None
        elif report_output.startswith('sys://'):
            pipe = report_output[6:]
            assert pipe in ('stdout', 'stderr')
            self.report_file = getattr(sys, pipe)
        else:
            self.report_file = open(report_output, 'w')

    def begin(self):
        # XXX: this is pretty hacky
        self.db = CoverageDB(self.config.db, self.logger)
        if self.config.record:
            self.db.upgrade()

        if self.config.report or self.config.record:
            # If we're recording coverage we need to ensure it gets reset
            self.coverage = self._setup_coverage()

        if not (self.config.discover or self.config.record):
            return

        proc = Popen(['git', 'merge-base', 'HEAD', self.config.parent], stdout=PIPE, stderr=STDOUT)
        self.parent_revision = proc.stdout.read().strip()

        if self.config.record:
            # Use our current revision
            self.logger.info("Recording current revision")
            proc = Popen(['git', 'log', '-n 1', '--format=%H %ct'], stdout=PIPE, stderr=STDOUT)
            self.revision, commit_date = proc.stdout.read().strip().split(' ')
            commit_date = datetime.datetime.fromtimestamp(int(commit_date))
            self.revision_id = self.db.add_revision(self.revision, commit_date)

        elif self.config.discover:
            # We need to determine our merge base
            self.logger.info("Checking coverage for revision %s", self.parent_revision)
            self.revision = self.parent_revision
            try:
                self.revision_id = self.db.get_revision_id(self.revision)
            except ValueError:
                raise ValueError('Revision not recorded in coverage database (do you need to rebase?)')

        if not (self.config.discover or self.config.report):
            return

        s = time.time()
        self.logger.info("Parsing diff from parent %s", self.parent_revision)
        # pull in our diff
        # git diff `git merge-base HEAD master`
        proc = Popen(['git', 'diff', self.parent_revision], stdout=PIPE, stderr=STDOUT)
        diff = proc.stdout.read().strip()

        pending_funcs = self.pending_funcs

        parser = DiffParser(diff)
        files = list(parser.parse())

        diff = self.diff_data
        s = time.time()
        for file in files:
            # we dont care about headers
            if file['is_header']:
                continue

            # file was removed
            if file['new_filename'] == '/dev/null':
                continue

            is_new_file = (file['old_filename'] == '/dev/null')
            if is_new_file:
                filename = file['new_filename']
                if not filename.startswith('b/'):
                    continue
            else:
                filename = file['old_filename']
                if not filename.startswith('a/'):
                    continue  # ??

            filename = filename[2:]

            # Ignore non python files
            if not is_py_script(filename):
                continue

            # file is new, only record diff state
            for chunk in file['chunks']:
                linenos = filter(bool, (l['new_lineno'] for l in chunk if l['line']))
                diff[file['new_filename'][2:]].update(linenos)

            # we dont care about missing coverage for new code, and there
            # wont be any "existing coverage" to check for
            if is_new_file:
                continue

            if not self.config.discover:
                continue

        self.logger.info("Parsed diff in %.2fs as %d file(s)", time.time() - s, len(diff))

        if self.config.discover:
            self.logger.info("Finding coverage for %d file(s)", len(files))

            for filename, linenos in diff.iteritems():
                test_coverage = self.db.get_coverage(self.revision_id, filename, linenos)
                if not test_coverage:
                    # check if we have any coverage recorded
                    if not self.db.has_coverage(self.revision_id, filename):
                        if self.config.skip_missing:
                            self.logger.warning('%s has no test coverage recorded', filename)
                            continue
                        raise AssertionError("Missing test coverage for %s" % filename)
                else:
                    for test in test_coverage:
                        pending_funcs.add(test)

            self.logger.info("Determined available coverage in %.2fs with %d test(s)", time.time() - s, len(pending_funcs))

    def report(self, stream):
        if not self.config.report:
            return

        cov_data = self.cov_data
        diff_data = self.diff_data

        covered = 0
        total = 0
        missing = defaultdict(set)
        for filename, linenos in diff_data.iteritems():
            covered_linenos = cov_data[filename]

            total += len(linenos)
            covered += len(covered_linenos)

            missing[filename] = linenos.difference(covered_linenos)

        if self.report_file:
            self.report_file.write(simplejson.dumps({
                'stats': {
                    'covered': covered,
                    'total': total,
                },
                'missing': dict((k, tuple(v)) for k, v in missing.iteritems() if v),
            }))
            self.report_file.close()
        elif total:
            stream.writeln('Coverage Report')
            stream.writeln('-' * 70)
            stream.writeln('Coverage against diff is %.2f%% (%d / %d lines)' % (covered / float(total) * 100, covered, total))
            if missing:
                stream.writeln()
                stream.writeln('%-35s   %s' % ('Filename', 'Missing Lines'))
                stream.writeln('-' * 70)
                for filename, linenos in missing.iteritems():
                    if not linenos:
                        continue
                    stream.writeln('%-35s   %s' % (filename, ', '.join(map(str, sorted(linenos)))))

    def wantMethod(self, method):
        if not self.config.discover:
            return

        # only works with unittest compatible functions currently
        method_name = method.__name__
        method = getattr(sys.modules[method.im_class.__module__], method.im_class.__name__)
        test_name = '%s:%s.%s' % (method.__module__, method.__name__, method_name)

        # test has coverage for diff
        if test_name in self.pending_funcs:
            return True

        # test has no coverage recorded, defer to other plugins
        elif self.config.test_missing and not self.db.has_test(self.revision_id, test_name):
            self.pending_funcs.add(test_name)
            self.logger.info("Allowing test due to missing coverage report: %s", test_name)
            return None

        return False

    def startTest(self, test):
        if not (self.config.record or self.config.report):
            return

        self.coverage.start()

    def stopTest(self, test):
        if not (self.config.record or self.config.report):
            return

        cov = self.coverage
        cov.stop()

        test_ = test.test
        test_name = self._get_name_from_test(test_)

        # this must have been imported under a different name
        # if self.discover and test_name not in self.pending_funcs:
        #     self.logger.warning("Unable to determine origin for test: %s", test_name)
        #     return

        # initialize reporter
        rep = Reporter(cov)

        # process all files
        rep.find_code_units(None, cov.config)

        # Compute the standard deviation for all code executed from this test
        linenos = []
        for filename in cov.data.measured_files():
            linenos.extend(cov.data.executed_lines(filename).values())

        # The rest of this is all run within a single transaction
        trans = self.db.begin()

        if self.config.record:
            self.db.remove_test(self.revision_id, test_name)
            test_id = self.db.add_test(self.revision_id, test_name)

        for cu in rep.code_units:
            # if sys.modules[test_.__module__].__file__ == cu.filename:
            #     continue
            filename = cu.name + '.py'
            linenos = cov.data.executed_lines(cu.filename)

            if self.config.record:
                linenos_in_prox = dict((k, v) for k, v in linenos.iteritems() if v < self.config.max_distance)
                if linenos_in_prox:
                    self.db.add_coverage(self.revision_id, test_id, filename, linenos_in_prox)

            if self.config.report:
                diff = self.diff_data[filename]
                cov_linenos = [l for l in linenos if l in diff]
                if cov_linenos:
                    self.cov_data[filename].update(cov_linenos)

        trans.commit()

        cov.erase()

