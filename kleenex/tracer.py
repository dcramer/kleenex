"""
kleenex.tracer
~~~~~~~~~~~~~~

:copyright: 2011 DISQUS.
:license: BSD
"""

from coverage.collector import PyTracer


class ExtendedTracer(PyTracer):
    def __init__(self):
        PyTracer.__init__(self)
        self.frame_depth = 0

    def _trace(self, frame, event, arg_unused):
        """The trace function passed to sys.settrace."""

        #print("trace event: %s %r @%d" % (
        #           event, frame.f_code.co_filename, frame.f_lineno))

        if self.last_exc_back:
            if frame == self.last_exc_back:
                # Someone forgot a return event.
                if self.arcs and self.cur_file_data:
                    pair = (self.last_line, -self.last_exc_firstlineno)
                    self.cur_file_data[pair] = self.frame_depth
                self.cur_file_data, self.last_line, self.frame_depth = self.data_stack.pop()
            self.last_exc_back = None

        if event == 'call':
            # Entering a new function context.  Decide if we should trace
            # in this file.
            self.data_stack.append((self.cur_file_data, self.last_line, len(self.data_stack)))
            filename = frame.f_code.co_filename
            tracename = self.should_trace_cache.get(filename)
            if tracename is None:
                tracename = self.should_trace(filename, frame)
                self.should_trace_cache[filename] = tracename
            #print("called, stack is %d deep, tracename is %r" % (
            #               len(self.data_stack), tracename))
            if tracename:
                if tracename not in self.data:
                    self.data[tracename] = {}
                self.cur_file_data = self.data[tracename]
            else:
                self.cur_file_data = None
            # Set the last_line to -1 because the next arc will be entering a
            # code block, indicated by (-1, n).
            self.last_line = -1
        elif event == 'line':
            # Record an executed line.
            if self.cur_file_data is not None:
                if self.arcs:
                    #print("lin", self.last_line, frame.f_lineno)
                    self.cur_file_data[(self.last_line, frame.f_lineno)] = self.frame_depth
                else:
                    #print("lin", frame.f_lineno)
                    self.cur_file_data[frame.f_lineno] = self.frame_depth
            self.last_line = frame.f_lineno
        elif event == 'return':
            if self.arcs and self.cur_file_data:
                first = frame.f_code.co_firstlineno
                self.cur_file_data[(self.last_line, -first)] = self.frame_depth
            # Leaving this function, pop the filename stack.
            self.cur_file_data, self.last_line, self.frame_depth = self.data_stack.pop()
            #print("returned, stack is %d deep" % (len(self.data_stack)))
        elif event == 'exception':
            #print("exc", self.last_line, frame.f_lineno)
            self.last_exc_back = frame.f_back
            self.last_exc_firstlineno = frame.f_code.co_firstlineno
        return self._trace
