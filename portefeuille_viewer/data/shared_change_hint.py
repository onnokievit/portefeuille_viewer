"""Local advisory wake-up; committed DB revisions remain the source of truth."""
import logging
import os
from uuid import uuid4

from portefeuille_viewer.config.local_runtime import runtime_root, resource_id
from portefeuille_viewer.config.process_lock import canonical_path


def hint_path(database):
    return runtime_root() / ('stock-change-' + resource_id(canonical_path(database)) + '.token')


def read_hint(path):
    try:
        return path.read_text(encoding='ascii')
    except OSError:
        return None


def publish_hint(database):
    """A hint failure must never turn a successful commit into an apparent failure."""
    temporary = None
    try:
        target = hint_path(database)
        token = uuid4().hex
        temporary = target.with_suffix('.tmp-' + token)
        temporary.write_text(token, encoding='ascii')
        os.replace(temporary, target)
    except OSError:
        logging.warning('Local STOCKDATA notification failed; periodic DB check will recover', exc_info=True)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
