"""
nose_bleed.diff
~~~~~~~~~~~~~~~

This is an adaptation from lodgeit's lib/diff.py

:copyright: 2007 by Armin Ronacher.
:license: BSD
"""

import re

from cgi import escape

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

        return files, info

    def parse(self):
        return self._parse_udiff()