"""Zero-dependency unittest adapter for pytest-style test_* functions (with optional tmp_path)."""
import inspect
import os
import tempfile
import unittest
from pathlib import Path


def make_suite(module) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("test_"):
            continue

        sig = inspect.signature(obj)
        needs_tmp = "tmp_path" in sig.parameters

        def _make_test(fn, with_tmp: bool):
            def _run(self):
                old_env = os.environ.copy()
                try:
                    if with_tmp:
                        with tempfile.TemporaryDirectory() as td:
                            fn(Path(td))
                    else:
                        fn()
                finally:
                    os.environ.clear()
                    os.environ.update(old_env)
            _run.__name__ = fn.__name__
            return _run

        cls = type(
            f"Test_{name}",
            (unittest.TestCase,),
            {name: _make_test(obj, needs_tmp)},
        )
        suite.addTest(cls(name))
    return suite
