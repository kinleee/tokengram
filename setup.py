"""
setup.py — minimal shim that tags the wheel as platform-specific.

All project metadata lives in pyproject.toml ([project]). This file exists
ONLY to mark the distribution as carrying compiled extension modules, so that
`python -m build` tags the wheel for the host platform
(cp312-cp312-win_amd64 / cp312-cp312-manylinux_* / cp312-cp312-macosx_*)
instead of the misleading `py3-none-any`.

Why this is needed
------------------
Our engine ships as prebuilt extension files declared as package-data in
pyproject.toml: .pyd on Windows, .so on Linux/macOS (built ahead of time by
setup_cython.py). Because pyproject declares no `ext_modules`, setuptools would
otherwise treat the package as pure Python and tag the wheel `py3-none-any` —
a tag that claims "runs on any platform" while the binaries inside only load on
the platform they were compiled for.

That mislabel caused two concrete problems:
  1. A Windows-built wheel would pip-install on Linux/macOS and then crash on
     import (it contains win_amd64 .pyd that those platforms cannot load).
  2. We could not ship one wheel per platform — every platform produced the
     same `tokengram-X.Y.Z-py3-none-any.whl` filename, which collides on PyPI
     and inside the extension's resources/ folder.

Overriding has_ext_modules() forces the correct platform tag WITHOUT compiling
anything here. Nothing in the Windows build path changes except the (now
honest) wheel tag; the extension installs the bundled wheel by file path, and a
correctly-tagged wheel installs on its matching platform exactly as before.
"""
from setuptools import setup
from setuptools.dist import Distribution


class BinaryDistribution(Distribution):
    """A distribution that always reports compiled extensions are present.

    This is what flips bdist_wheel from the pure-Python `py3-none-any` tag to a
    platform-specific tag. We do not list `ext_modules` (the .pyd/.so are
    prebuilt), so setuptools does not attempt to compile anything during build.
    """

    def has_ext_modules(self) -> bool:
        return True


setup(distclass=BinaryDistribution)
