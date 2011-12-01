nose-bleed
==========

**Under Development!**

nose-bleed attempts to stop the pain associated with a large test suite by
only running the tests applicable to the changes in your [git] branch.

Usage
-----

(This will change soon)

You will first need to run your test suite with ``--record-test-coverage``, to
plot initial function coverage.

Once this is done, nose-bleed will keep coverage up to date everytime it runs itself (j/k this is actually broken
atm).

After the coverage has been built, you can commit your changes within a git
branch and run ``--discover`` to filter out any tests which dont provide
coverage for changes. Currently, the changes are based on the "origin/master" branch.

nose-bleed also checks for missing coverage along the way. By default it will raise an error when it hits a code
change that has no test coverage. To disable this functionality, you should set ``--skip-missing-coverage``.
