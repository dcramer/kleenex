kleenex
=======

**Under Development!**

kleenex attempts to stop the pain associated with a large test suite by
only running the tests applicable to the changes in your [git] branch.

About
-----

Assuming ``--with-kleenex``, kleenex is fully active on all test runs. What this means, is it will attempt
to connect to a coverage database (sqlite:///coverage.db by default) and determine which tests it needs to run
based on the code changes. If data for a test is missing in the database (e.g. the test is new), it will include
that test in the suite automatically. This is fine for prototyping but not generally useful in the real world.

Kleenex also checks for missing coverage along the way. By default it will raise an error when it hits a code
change that has no test coverage. To disable this functionality, you should set ``--kleenex-skip-missing``.

Real World Usage
----------------

Kleenex is designed to work in CI environments. Generally, you would setup your CI server to run it in record
mode (with ``--kleenex-record``), and your clients (yourself, other developers) would simply connect to this
database to discover coverage. This ensures that the installation stays aware of your parent branch (e.g. master)
and doesn't record data from children.
