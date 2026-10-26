"""Load existing domain packages without sharing their generic import names."""
import importlib.util
import pathlib
import sys
import threading

_lock = threading.RLock()


def load_package(alias, package_dir):
    """Keep each source checkout authoritative and reject namespace collisions."""
    package_dir = pathlib.Path(package_dir).resolve(strict=True)
    entry = package_dir / '__init__.py'
    if not entry.is_file() or not alias.isidentifier():
        raise ValueError('Invalid department package')
    with _lock:
        existing = sys.modules.get(alias)
        if existing is not None:
            if pathlib.Path(existing.__file__).resolve() != entry:
                raise ValueError('Department package is already bound to another source')
            return existing
        spec = importlib.util.spec_from_file_location(alias, entry,
                                                     submodule_search_locations=[str(package_dir)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[alias] = package
        try:
            spec.loader.exec_module(package)
        except Exception:
            sys.modules.pop(alias, None)
            raise
        return package
