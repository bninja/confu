import os
import StringIO

import mock
import pytest

import confu


@pytest.fixture(scope='function')
def locations(request):
    paths = {
        os.path.expanduser('~/.confu.cfg'): """\
[cfn]
parameters[KeyName] = ai-gazelle
""",
        os.path.abspath('.confu.cfg'): """\
[default]
profile = julius

[aws]
regions = us-west-1
default_region = us-west-1

[cfn]
bucket_format = {profile}-confu-cfn-{region}
bucket_key = vault
stack_name_format = {Prefix}-{AppEnv}-{random}
parameters[InfraSilo] = vault
parameters[ConfName] = infra-julius
parameters[ConfSource] = {profile}-confu-pkg
stack_tags[infra-silo] = vault

[pkg]
bucket_format = {profile}-confu-pkg
includes =
  infras/
  !infras/global/mq.yml
  !infras/global/site.yml
  !infras/global/.confu.cfg
  !infras/global/inventories/
  !infras/global/formations/
  !infras/global/roles/
  inventories/
  ops/

[atlas]
source_dir = infras/global/atlas
"""
    }

    def _exists(path):
        return path in paths

    patch = mock.patch('confu.settings.os.path.exists', _exists)
    patch.start()
    request.addfinalizer(patch.stop)

    def _open(path, *args, **kwargs):
        return StringIO.StringIO(paths[path])

    patch = mock.patch('__builtin__.open', _open, create=True)
    patch.start()
    request.addfinalizer(patch.stop)


def test_merge(locations):
    assert confu.settings.load(globalize=False) == {
        'atlas': {
            'source_dir': 'infras/global/atlas'
        },
        'aws': {'default_region': 'us-west-1', 'regions': ['us-west-1']},
        'cfn': {
            'bucket_format': '{profile}-confu-cfn-{region}',
            'bucket_key': 'vault',
            'parameters': {
                'ConfName': 'infra-julius',
                'ConfSource': '{profile}-confu-pkg',
                'InfraSilo': 'vault',
                'KeyName': 'ai-gazelle'
            },
            'stack_name_format': '{Prefix}-{AppEnv}-{random}',
            'stack_tags': {'infra-silo': 'vault'}},
        'pkg': {
            'bucket_format': '{profile}-confu-pkg',
            'default_includes': [
                'group_vars/',
                'host_vars/',
                'roles/',
                '/ansible.cfg',
                '!*/ansible.cfg',
                '*.yml',
                '!.project',
                '!*.git',
                '!*.pyc',
                '!*.pyo',
                '!*.git*',
                '!*.travis.yml',
                '!*.md',
                '!Vagrantfile',
                '!*/test/',
                '!test.yml'
            ],
            'includes': [
                'infras/',
                '!infras/global/mq.yml',
                '!infras/global/site.yml',
                '!infras/global/.confu.cfg',
                '!infras/global/inventories/',
                '!infras/global/formations/',
                '!infras/global/roles/',
                'inventories/',
                'ops/',
            ],
            'name': '{source.dir_name}',
            'source_dir': './',
            'stage_dir': '/tmp/confu/{package.name}-{package.version}',
            'version': '{source.git_version}'
        },
        'profile': 'julius',
        'region': 'us-west-1'
    }
