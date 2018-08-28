"""
Helpers for using these infrastructure tools:

- `troposphere <https://github.com/cloudtools/troposphere>`_
- `aws cfn <http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html>`_
- `ansible <http://docs.ansible.com/>`_

"""
__version__ = '0.1.10'

__all__ = [
    'ansible',
    'aws',
    'cfn',
    'cli',
    'pkg',
    'settings',
]

import imp
import json
import logging
import os
import sys


logger = logging.getLogger(__name__)


def logging_at(level=logging.ERROR):
    if isinstance(level, basestring):
        levels = {
            'd': logging.DEBUG, 'debug': logging.DEBUG,
            'i': logging.INFO, 'info': logging.INFO,
            'w': logging.WARN, 'warn': logging.WARN, 'warning': logging.WARN,
            'e': logging.ERROR, 'error': logging.ERROR,
        }
        if level not in levels:
            raise ValueError(
                '{0} invalid, expected one of {1}'.format(level, levels.keys())
            )
        level = levels[level]
    elif not isinstance(level, (int, long)):
        raise TypeError('level={0!r} must be string or int'.format(level))
    logging.basicConfig(
        level=level,
        format='%(asctime)s : %(levelname)s : %(name)s : %(message)s',
        stream=sys.stderr,
    )


from . import settings
from . import aws
from .cli import cli
from . import ansible
from . import cfn
from . import pkg
from . import shell


@cli.command('cfg')
def cfg():
    summary = {
        'profile': settings.profile,
        'region': settings.region,
        'aws': settings.aws,
        'cfn': settings.cfn,
        'pkg': settings.pkg,
        'atlas': settings.atlas,
    }
    print json.dumps(summary, indent=4, sort_keys=True)


class ImportAtlas(object):
    """
    Import hook for ``confu.atlas`` that:

    - loads settings based on environment
    - applies them
    - imports the registered atlas package

    An ``atlas`` is typically just:

    - python package containing common troposphere patterns
    - registered as a package path via ``confu.settings.atlas``

    """

    @classmethod
    def find_module(cls, fullname, path=None):
        if fullname != 'confu.atlas':
            return
        return cls(fullname, path)

    def __init__(self, fullname, path):
        self.fullname = fullname
        self.path = path

    def load_module(self, name):
        settings.load(
            profile=os.environ.get('CONFU_PROFILE') or None,
            region=os.environ.get('CONFU_REGION') or None,
        )
        aws.cxn.activate(
            profile_name=settings.profile,
            default_region=settings.region,
        )
        logger.info('importing "%s" from "%s"', self.fullname, settings.atlas.source_dir)
        module = imp.load_module(
            name, None, settings.atlas.source_dir, ('', 'r', imp.PKG_DIRECTORY)
        )
        return module

sys.meta_path.append(ImportAtlas)
