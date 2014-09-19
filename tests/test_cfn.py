import os
import stat
import subprocess

import pytest

import confu


def make_executable(file_path):
    st = os.stat(file_path)
    os.chmod(file_path, st.st_mode | stat.S_IEXEC)


class TestTemplateScript(object):

    def test_missing(self):
        tpl = confu.cfn.TemplateScript('./nonsense')
        with pytest.raises(Exception) as ex_info:
            tpl.body
        assert './nonsense' in str(ex_info.value)

    def test_not_executable(self, tmp_file):
        tpl = confu.cfn.TemplateScript(tmp_file)
        with pytest.raises(Exception) as ex_info:
            tpl.body
        assert tmp_file in str(ex_info.value)
        assert '*not* executable' in str(ex_info.value)

    def test_bogus_executable(self, tmp_file):
        make_executable(tmp_file)
        tpl = confu.cfn.TemplateScript(tmp_file)
        with pytest.raises(OSError):
            tpl.body

    def test_failure(self, tmp_file):
        make_executable(tmp_file)
        with open(tmp_file, 'w+') as fo:
            fo.write("""\
#!/usr/bin/env python
boom
""")
        tpl = confu.cfn.TemplateScript(tmp_file)
        with pytest.raises(subprocess.CalledProcessError) as ex_info:
            tpl.body
        assert tmp_file in str(ex_info.value)

    def test_not_json(self, tmp_file):
        make_executable(tmp_file)
        with open(tmp_file, 'w+') as fo:
            fo.write("""\
#!/usr/bin/env python
from __future__ import print_function

print("{'bad': json}", end=""),
""")
        tpl = confu.cfn.TemplateScript(tmp_file)
        with pytest.raises(ValueError):
            tpl.body

    def test_ok(self, tmp_file):
        make_executable(tmp_file)
        with open(tmp_file, 'w+') as fo:
            fo.write("""\
#!/usr/bin/env python
from __future__ import print_function

print("{}", end="")
""")
        tpl = confu.cfn.TemplateScript(tmp_file)
        assert tpl.body == {}
