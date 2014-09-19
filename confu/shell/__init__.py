import os

from click._bashcomplete import bashcomplete

from .. import cli


@cli.group()
def shell():
    pass


@shell.command('env')
def env():
    script_path = os.path.join(os.path.dirname(__file__), 'confue.bash')
    print open(script_path, 'r').read()


@shell.command('complete')
def complete():
    bashcomplete(cli, 'confu', '_CONFU_COMPLETE', 'source')
