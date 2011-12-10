kleenex
=======

**Under Development!**

kleenex attempts to stop the pain associated with a large test suite by
only running the tests applicable to the changes in your [git] branch.

Usage
-----

By default, kleenex is fully active on all test runs. What this means, is it will attempt to connect to a
coverage database (sqlite://coverage.db by default) and determine which tests it needs to run based on the
code changes. If data for a test is missing in the database (e.g. the test is new), it will include that test
in the suite automatically.

Kleenex also checks for missing coverage along the way. By default it will raise an error when it hits a code
change that has no test coverage. To disable this functionality, you should set ``--skip-missing-coverage``.

Recording Test Coverage
-----------------------

In order to utilize selective test runner, you're going to need to continually populate a coverage database.
Generally the best way to do this is to have something like your CI server always run with --record-test-coverage
on your master (develop) branch.