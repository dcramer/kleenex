from unittest2 import TestCase

from kleenex.db import CoverageDB

import logging
import os.path


class CoverageDBTest(TestCase):
    def setUp(self):
        self.db = CoverageDB('sqlite:///test.db', logger=logging.getLogger(__name__))
        self.db.upgrade()

    def tearDown(self):
        os.unlink('test.db')

    def test_has_seen(self):
        self.assertFalse(self.db.has_test('foo.bar'))
        self.db.set_test_has_seen_test('foo.bar', '1')
        self.assertTrue(self.db.has_test('foo.bar'))
