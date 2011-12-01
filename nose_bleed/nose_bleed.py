from __future__ import absolute_import

import cPickle as pickle
import logging
import os
import re
import sys
import time
import traceback

from cgi import escape
from coverage import coverage
from coverage.report import Reporter
from nose.plugins.base import Plugin
from subprocess import Popen, PIPE

COVERAGE_DATA_FILE = 'test_coverage.pickle'

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

class DiffParser(object):
    """
    This is based on code from the open source project, "lodgeit".
    """
    _chunk_re = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

    def __init__(self, udiff):
        """:param udiff:   a text in udiff format"""
        self.lines = [escape(line) for line in udiff.splitlines()]

    def _extract_rev(self, line1, line2):
        def _extract(line):
            parts = line.split(None, 1)
            return parts[0], (len(parts) == 2 and parts[1] or None)
        try:
            if line1.startswith('--- ') and line2.startswith('+++ '):
                return _extract(line1[4:]), _extract(line2[4:])
        except (ValueError, IndexError):
            pass
        return (None, None), (None, None)

    def _highlight_line(self, line, next):
        """Highlight inline changes in both lines."""
        start = 0
        limit = min(len(line['line']), len(next['line']))
        while start < limit and line['line'][start] == next['line'][start]:
            start += 1
        end = -1
        limit -= start
        while -end <= limit and line['line'][end] == next['line'][end]:
            end -= 1
        end += 1
        if start or end:
            def do(l):
                last = end + len(l['line'])
                if l['action'] == 'add':
                    tag = 'ins'
                else:
                    tag = 'del'
                l['line'] = u'%s<%s>%s</%s>%s' % (
                    l['line'][:start],
                    tag,
                    l['line'][start:last],
                    tag,
                    l['line'][last:]
                )
            do(line)
            do(next)

    def _parse_info(self):
        """Look for custom information preceding the diff."""
        nlines = len(self.lines)
        if not nlines:
            return
        firstline = self.lines[0]
        info = []

        # look for Hg export changeset
        if firstline.startswith('# HG changeset patch'):
            info.append(('Type', 'HG export changeset'))
            i = 0
            line = firstline
            while line.startswith('#'):
                if line.startswith('# User'):
                    info.append(('User', line[7:].strip()))
                elif line.startswith('# Date'):
                    try:
                        t, tz = map(int, line[7:].split())
                        info.append(('Date', time.strftime(
                            '%b %d, %Y %H:%M:%S', time.gmtime(float(t) - tz))))
                    except Exception:
                        pass
                elif line.startswith('# Branch'):
                    info.append(('Branch', line[9:].strip()))
                i += 1
                if i == nlines:
                    return info
                line = self.lines[i]
            commitmsg = ''
            while not line.startswith('diff'):
                commitmsg += line + '\n'
                i += 1
                if i == nlines:
                    return info
                line = self.lines[i]
            info.append(('Commit message', '\n' + commitmsg.strip()))
            self.lines = self.lines[i:]
        return info

    def _parse_udiff(self):
        """Parse the diff an return data for the template."""
        info = self._parse_info()

        in_header = True
        header = []
        lineiter = iter(self.lines)
        files = []
        try:
            line = lineiter.next()
            while 1:
                # continue until we found the old file
                if not line.startswith('--- '):
                    if in_header:
                        header.append(line)
                    line = lineiter.next()
                    continue

                if header and all(x.strip() for x in header):
                    files.append({'is_header': True, 'lines': header})
                    header = []

                in_header = False
                chunks = []
                old, new = self._extract_rev(line, lineiter.next())
                files.append({
                    'is_header':        False,
                    'old_filename':     old[0],
                    'old_revision':     old[1],
                    'new_filename':     new[0],
                    'new_revision':     new[1],
                    'chunks':           chunks
                })

                line = lineiter.next()
                while line:
                    match = self._chunk_re.match(line)
                    if not match:
                        in_header = True
                        break

                    lines = []
                    chunks.append(lines)

                    old_line, old_end, new_line, new_end = \
                        [int(x or 1) for x in match.groups()]
                    old_line -= 1
                    new_line -= 1
                    old_end += old_line
                    new_end += new_line
                    line = lineiter.next()

                    while old_line < old_end or new_line < new_end:
                        if line:
                            command, line = line[0], line[1:]
                        else:
                            command = ' '
                        affects_old = affects_new = False

                        if command == '+':
                            affects_new = True
                            action = 'add'
                        elif command == '-':
                            affects_old = True
                            action = 'del'
                        else:
                            affects_old = affects_new = True
                            action = 'unmod'

                        old_line += affects_old
                        new_line += affects_new
                        lines.append({
                            'old_lineno':   affects_old and old_line or u'',
                            'new_lineno':   affects_new and new_line or u'',
                            'action':       action,
                            'line':         line
                        })
                        line = lineiter.next()

        except StopIteration:
            pass

        # highlight inline changes
        for file in files:
            if file['is_header']:
                continue
            for chunk in file['chunks']:
                lineiter = iter(chunk)
                try:
                    while True:
                        line = lineiter.next()
                        if line['action'] != 'unmod':
                            nextline = lineiter.next()
                            if nextline['action'] == 'unmod' or \
                               nextline['action'] == line['action']:
                                continue
                            self._highlight_line(line, nextline)
                except StopIteration:
                    pass

        return files, info

    def parse(self):
        return self._parse_udiff()

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

        parser.add_option("--discover",
                          dest="discover", action="store_true",
                          default=None)

    def configure(self, options, config):
        self.enabled = (options.record_test_coverage or options.discover)
        self.discover = options.discover
        self.logger = logging.getLogger(__name__)

    def begin(self):
        self.base_path = os.path.normpath(os.path.join(os.path.dirname(sys.modules['disqus'].__file__), os.pardir)) + '/'

        if os.path.exists(COVERAGE_DATA_FILE):
            self.logger.info("Loading pickled coverage data from %s..", COVERAGE_DATA_FILE)
            s = time.time()
            self.test_coverage = pickle.load(open(COVERAGE_DATA_FILE, 'rb'))
            self.logger.info("Loaded coverage data in %.2fs", time.time() - s)

        elif self.discover:
            raise ValueError('You cannot use --discover without having done --record-test-coverage first.')
        else:
            self.test_coverage = {}

        if not self.discover:
            return

        # pull in our diff
        # git diff `git merge-base HEAD master`
        proc = Popen('git merge-base HEAD origin/master'.split(), stdout=PIPE)
        parent = proc.stdout.read()
        proc = Popen(('git diff %s' % parent).split(), stdout=PIPE)
        diff = proc.stdout.read()

        pending_funcs = self.pending_funcs = set()

        self.logger.info("Parsing diff from parent %s", parent)
        s = time.time()
        parser = DiffParser(diff)
        files, info = parser.parse()
        self.logger.info("Parsed diff in %.2fs", time.time() - s)

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
                self.logger.warning('%s has no test coverage recorded', filename)
                continue

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

    def wantMethod(self, method):
        if not self.discover:
            return
        # only works with unittest compatible functions currently
        func_name = '%s:%s.%s' % (method.im_class.__module__, method.im_class.__name__, method.__name__)
        if func_name in self.pending_funcs:
            return True
        return False

    def finalize(self, result):
        pickle.dump(self.test_coverage, open(COVERAGE_DATA_FILE, 'wb'))

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
                filename = cu.filename.replace(self.base_path, '')
                analysis = rep.coverage._analyze(cu)
                if filename not in units:
                    units[filename] = {}
                for lineno in analysis.statements:
                    units[filename].setdefault(lineno, set())
                    units[filename][lineno].add(test_name)
            except KeyboardInterrupt:                       # pragma: no cover
                raise
            except:
                traceback.print_exc()
                if not rep.ignore_errors:
                    typ, msg = sys.exc_info()[:2]

