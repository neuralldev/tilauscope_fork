"""Start BeanCave alone, beside the operator's own Artisan (packaged entry point)."""

import io
import os
import sys

if getattr(sys, 'frozen', False):
    # A windowed bundle has no console: logging and print must not crash on None.
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

os.environ['OMP_NUM_THREADS'] = '1'

from tilauscope.beancave_app import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
