"""
Builds Ansible *site* packages that can be used to configure a machine. They
consist of:

- `ansible playbooks <http://docs.ansible.com/playbooks_best_practices.html#content-organization>`_

and the:

- relocatable python `virtual environment <https://virtualenv.pypa.io/en/latest/>_`

needed to run them. Packages are described by:

    - `Package`
    - `Source`
    - `Pattern`

the build process by:

    - `Makefile`

and exposed to you like:

.. code:: bash

    $ confu pkg --help

You can use built archives directly to configure a machine, e.g. for
``my-conf-0.1.2.tar.gz``:

.. code:: bash

    local$ scp my-conf-0.1.2.tar.gz me@host:
    local$ tar xvf me@host
    local$ ssh me@host
    host$ tar xvf my-conf-0.1.2.tar.gz -C /opt/
    host$ cd /opt/my-conf-0.1.2/
    host$ ./env/bin/ansible-playbook site.yml -i inventories/pull -c local

or use them to build distribution packages (e.g. RPMs, DEBs).

.. note::

    Archives are tied to your build environment (e.g. distro version,
    architecture, etc) so target machines to configure need to be similar.

"""
import distutils
import errno
import fnmatch
import json
import logging
import os
import re
import string
import subprocess
import sys
import tempfile

import boto.s3
import click

from . import settings, aws, cli


logger = logging.getLogger(__name__)


class Package(object):

    default_patterns = [
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
        '!test.yml',
    ]

    def __init__(self,
                 source_dir,
                 name='{source.dir_name}',
                 version='{source.git_version}',
                 stage_dir=None,
                 patterns=None,
                 bucket_format=None,
        ):
        self.source = Source(os.path.abspath(source_dir))
        self.name = name.format(source=self.source)
        self.version = version.format(source=self.source)
        self.stage_dir = (
            stage_dir or
            os.path.join(
                tempfile.gettempdir(),
                'confu',
                '{package.name}-{package.version}'
            )
        ).format(source=self.source, package=self)
        self.patterns = [
            Pattern.from_expression(expression)
            for expression in patterns or self.default_patterns
        ]
        self.bucket_format = bucket_format

    def include(self, path, is_file):
        include = None
        for pattern in self.patterns:
            if pattern.match(path, is_file):
                include = not pattern.negate
                if pattern.negate:
                    break
        return include

    @property
    def manifest(self):
        paths = []
        for root, dirs, files in os.walk(self.source.dir):
            # match files
            for file in files:
                path = os.path.relpath(os.path.join(root, file), self.source.dir)
                if self.include(path, is_file=True) is True:
                    paths.append(path)

            # recurse prune
            recurse = []
            for dir in dirs:
                path = os.path.relpath(os.path.join(root, dir), self.source.dir)
                if self.include(path, is_file=False) is not False:
                    recurse.append(dir)
            dirs[:] = recurse

        return paths

    @property
    def makefile(self):
        return Makefile(self)

    def install_deps(self):
        """Install dependency roles

        """
        if not os.path.exists('ansible-requirements.yml'):
            logger.info('ansible-requirements.yml does not exist')
            return
        logger.info('installing dependency roles')
        subprocess.check_call([
            'ansible-galaxy', 'install',
            '-r', 'ansible-requirements.yml',
            '-p', '.',
            '--force',
        ])

    def stage(self):
        if not os.path.exists(self.stage_dir):
            logger.info('creating  stage dir %s', self.stage_dir)
            os.makedirs(self.stage_dir)
        manifest_file = os.path.join(self.stage_dir, '.manifest')
        with open(manifest_file, 'w+') as fo:
            logger.info('writing file manifest to %s', manifest_file)
            fo.writelines([line + '\n' for line in self.manifest])
        make_file = os.path.join(self.stage_dir, 'Makefile')
        with open(make_file, 'w+') as fo:
            logger.info('writing Makefile to %s', make_file)
            fo.write(self.makefile.render())

    @property
    def distribution(self):
        return os.path.join(
            self.source.dir,
            '{name}-{version}.tar.gz'.format(name=self.name, version=self.version)
        )

    @property
    def bucket_name(self):
        return self.bucket_format.format(**{
            'profile': settings.profile,
            'region': settings.region,
        })

    @property
    def archive_bucket(self):
        return aws.get_s3_bucket(
            self.bucket_name, region=settings.region, create=True,
        )

    def archive(self, always=False):
        if not os.path.isfile(self.distribution):
            if not always:
                raise OSError((errno.ENOENT, self.distribution))
            logger.info('"%s" not found, trying to create', self.distribution)
            self.stage()
            self.makefile.run('all')
            return self.archive(always=False)
        key_name = os.path.basename(self.distribution)
        bucket = self.archive_bucket
        key = boto.s3.key.Key(bucket, key_name)
        with open(self.distribution, 'rb') as fo:
            logger.info(
                'uploading "%s" to s3://%s/%s',
                self.distribution, self.archive_bucket.name, key_name
            )
            key.set_contents_from_file(fo)
        return aws.url_for_s3_key(key, auth=True)

    @property
    def archived_keys(self):
        prefix = '{0}-'.format(self.name)
        return [
           key for key in self.archive_bucket.list()
           if key.name.startswith(prefix)
        ]

    def archived_key(self, name):
        return self.archive_bucket.get_key(name)

    def archived_url(self, key, auth=False):
        if isinstance(key, basestring):
            key = self.archived_key(key)
        return aws.url_for_s3_key(key, auth)


class Pattern(object):

    @classmethod
    def from_expression(self, value):
        negate = False
        if value.startswith('!'):
            value = value[1:]
            negate = True
        if value.endswith('/'):
            value = value[:-1]
            cls = PrefixPattern
        else:
            cls = GlobPattern
        return cls(value, negate=negate)

    def __init__(self, negate):
        self.negate = negate

    def match(self, path, is_file):
        raise NotImplementedError

    @property
    def expression(self):
        pass

    def __unicode__(self):
        return self.expression

    def __str__(self):
        return self.__unicode__().encode('utf-8')


class GlobPattern(Pattern):

    def __init__(self, pattern, negate):
        self.pattern = pattern
        self.re = re.compile(fnmatch.translate(pattern.lstrip('/')))
        self.name_only = '/' not in pattern
        super(GlobPattern, self).__init__(negate)

    def match(self, path, is_file):
        if self.name_only:
            path = os.path.basename(path)
        return self.re.match(path) is not None

    @property
    def expression(self):
        return ('!' if self.negate else '') + self.pattern


class PrefixPattern(Pattern):

    def __init__(self, prefix, negate):
        self.prefix = prefix
        super(PrefixPattern, self).__init__(negate)

    def match(self, path, is_file):
        if is_file:
            return path.startswith(self.prefix)
        return path.startswith(self.prefix) or path + '/' == self.prefix

    @property
    def expression(self):
        return ('!' if self.negate else '') + self.prefix + '/'


class Source(object):

    def __init__(self, dir):
        self.dir = dir

    @property
    def dir_name(self):
        return os.path.basename(self.dir)

    @property
    def git_version(self):
        cmd = ['git', 'describe', '--always']
        logger.info('git_version - "%s"', ' '.join(cmd))
        return subprocess.check_output(cmd, cwd=self.dir).strip()


class Makefile(object):

    template = string.Template("""\
NAME = $name
VER = $version

SOURCEDIR = $source_dir

VENV = env
VENVBIN = $virtualenv_bin
VENVREQS = $$(SOURCEDIR)/requirements.txt
VENVRELOCATEBIN = $virtualenv_relocate_bin

STAGEDIR = $stage_dir
MANIFEST = $$(STAGEDIR)/.manifest
BUILDDIR = $$(STAGEDIR)/build

DISTDIR = $$(STAGEDIR)/dist
DISTNAME = $$(NAME)-$$(VER)
DISTFILE = $$(DISTNAME).tar.gz

.PHONY: build-files build-venv dist-sync dist-clean all clean

$$(BUILDDIR):
    mkdir -p $$@

build-files: $$(BUILDDIR)
    rsync -av --files-from=$$(MANIFEST) . $$(BUILDDIR)

build-venv: $$(BUILDDIR)
    $$(VENVBIN) $$(BUILDDIR)/$$(VENV)
    $$(BUILDDIR)/$$(VENV)/bin/pip install -r $$(VENVREQS)
    $$(BUILDDIR)/$$(VENV)/bin/pip uninstall pip setuptools -y
    $$(VENVBIN) --relocatable $$(BUILDDIR)/$$(VENV)
    $$(VENVRELOCATEBIN) $$(BUILDDIR)/$$(VENV) -ld

$$(DISTDIR):
    mkdir -p $$@

dist-sync: build-files build-venv $$(DISTDIR)
    rsync -av --exclude='*pyc' --exclude='*pyo' $$(BUILDDIR)/ $$(DISTDIR)/$$(DISTNAME)

$$(DISTFILE): dist-sync
    tar -czf $$(DISTDIR)/$$(DISTFILE) -C $$(DISTDIR) $$(DISTNAME)

dist-clean:
    rm -rf $$(DISTDIR)
    rm -rf $$(SOURCEDIR)/$$(DISTFILE)

$$(SOURCEDIR)/$$(DISTFILE): $$(DISTFILE)
    cp $$(DISTDIR)/$$(DISTFILE) $$(SOURCEDIR)/$$(DISTFILE)

all: $$(SOURCEDIR)/$$(DISTFILE)

clean: dist-clean
    rm -rf $$(STAGEDIR)

""".replace(' ' * 4, '\t'))

    def __init__(self, package):
        self.package = package

    def render(self):

        def find_executable(name):
            # if invoked from an interpreter w/o fiddling w/ path,
            # try to search distribution first, then fallback to default
            for search_path in [os.path.dirname(sys.executable), None]:
                executable = distutils.spawn.find_executable(name,
                                                             path=search_path)
                if executable:
                    return executable
            raise IOError(errno.ENOENT, 'No such file or directory', name)

        return self.template.substitute(
            name=self.package.name,
            version=self.package.version,
            source_dir=self.package.source.dir,
            stage_dir=self.package.stage_dir,
            virtualenv_bin=find_executable('virtualenv'),
            virtualenv_relocate_bin=find_executable('virtualenv-relocate')
        )

    def __unicode__(self):
        return self.render()

    def __str__(self):
        return self.__unicode__().encode('utf-8')

    def run(self, target):
        cmd = [
            'make',
            '-f', os.path.join(self.package.stage_dir, 'Makefile'),
            target
        ]
        logger.info('run(target="%s") - "%s"', target, ' '.join(cmd))
        return subprocess.call(cmd, stdout=sys.stdout, stderr=sys.stderr)


# cli.pkg

@cli.group('pkg')
@click.option('-n', '--name')
@click.option('-v', '--version')
@click.option('-s', '--source-dir')
@click.option('-b', '--bucket')
@click.pass_context
def pkg(ctx, name, version, source_dir, bucket):
    ctx.package = Package(
        source_dir=source_dir or settings.pkg.source_dir,
        name=name or settings.pkg.name,
        version=version or settings.pkg.version,
        patterns=settings.pkg.includes + settings.pkg.default_includes,
        bucket_format=bucket or settings.pkg.bucket_format
    )


@pkg.command('info')
@click.pass_context
def info(ctx):
    package = ctx.parent.package
    info = {
        'name': package.name,
        'version': package.version,
        'source': {
            'dir': package.source.dir,
        },
        'patterns': map(unicode, package.patterns),
        'stage_dir': package.stage_dir,
    }
    print json.dumps(info, indent=4, sort_keys=True)


@pkg.command('makefile')
@click.pass_context
def makefile(ctx):
    print ctx.parent.package.makefile


@pkg.command('manifest')
@click.pass_context
def manifest(ctx):
    for path in ctx.parent.package.manifest:
        print path


@pkg.command('init')
@click.pass_context
def init(ctx):
    ctx.parent.package.install_deps()


@pkg.command('stage')
@click.pass_context
def stage(ctx):
    ctx.parent.package.stage()


@pkg.command('build')
@click.pass_context
def build(ctx):
    ctx.parent.package.stage()
    sys.exit(ctx.parent.package.makefile.run('all'))


@pkg.command('clean')
@click.pass_context
def clean(ctx):
    ctx.parent.package.stage()
    sys.exit(ctx.parent.package.makefile.run('clean'))


@pkg.command('archive')
@click.option('-a', '--always', is_flag=True, default=False)
@click.pass_context
def archive(ctx, always):
    print ctx.parent.package.archive(always=always)


@pkg.command('archived')
@click.argument('name', required=False)
@click.option('--auth/--no-auth', default=None)
@click.pass_context
def archived(ctx, name, auth):

    def _url(key):
        print package.archived_url(key.name, auth)

    def _name(key):
        print key.name

    render = {
        True: _url,
        False: _url,
        None: _name,
    }[auth]

    package = ctx.parent.package

    if name is None:
        for key in package.archived_keys:
            render(key)
    elif any(c in name for c in '%?*'):
        for key in package.archived_keys:
            if fnmatch.fnmatch(key.name, name):
                render(key)
    else:
        key = package.archived_key(name)
        render(key, auth=auth)
