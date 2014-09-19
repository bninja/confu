import os
import shutil
import tempfile

import pytest

import confu


@pytest.fixture(scope='session', autouse=True)
def logging_config():
    confu.logging_at(os.environ.get('CONFU_TEST_LOG', 'info').lower())


@pytest.fixture()
def tmp_dir(request):
    path = tempfile.mkdtemp(prefix='confu-test-')
    request.addfinalizer(lambda: shutil.rmtree(path))
    return


@pytest.fixture()
def tmp_file(tmp_dir):
    fd, path = tempfile.mkstemp(dir=tmp_dir)
    os.close(fd)
    return path
