import ConfigParser
import json
import logging
import os
import tempfile

import boto.regioninfo
import pilo


logger = logging.getLogger(__name__)


class Region(pilo.fields.String):

    choices = [region.name for region in boto.regioninfo.get_regions('ec2')]

    def __init__(self, *args, **kwargs):
        super(Region, self).__init__(choices=self.choices, *args, **kwargs)


class Default(pilo.Form):

    #: Profile to use.
    profile = pilo.fields.String(default=None)


class AWS(pilo.Form):

    #: Support regions.
    regions = pilo.fields.List(Region(), default=lambda: Region.choices)

    #: Default region.
    default_region = Region(default=lambda: Region.choices[0])

    @default_region.validate
    def default_region(self, value):
        if value in self.regions:
            return True
        msg = '"{0}" must be one of {1}'.format(
            value, ', '.join(map(lambda x: '"{0}"'.format(x), self.regions))
        )
        self.ctx.errors.invalid(msg)
        return False


class CFN(pilo.Form):

    #: Format specification for template bucket names. It can reference:
    #: - ``profile``
    #: - ``region`
    bucket_format = pilo.fields.String(default='confu-cfn-{region}')

    #: Template bucket key (i.e. directory).
    bucket_key = pilo.fields.String(default='default')

    #: Format specification for stack names. It can reference:
    #: - any template parameter (e.g. `InfraEnv`).
    #: - ``random` which is just a random string.
    stack_name_format = pilo.fields.String(default='confu-{random}')

    #: Stack tags. Tag values can reference:
    #: - any template parameter (e.g. `InfraEnv`).
    #: Note that these will be prefixed with "confu:".
    stack_tags = pilo.fields.Dict(pilo.fields.String(), pilo.fields.String(), default=dict)

    #: Default parameters.
    parameters = pilo.fields.Dict(pilo.fields.String(), pilo.fields.String(), default=dict)


class PKG(pilo.Form):

    #: Path to source directory. Paths are expanded relative to containing file.
    source_dir = pilo.fields.String(default='./')

    @source_dir.munge
    def source_dir(self, value):
        if not self.ctx.src_path.location:
            return value
        start = os.path.dirname(self.ctx.src_path.location)
        return os.path.abspath(os.path.relpath(value, start))

    #: Format specification for the name of this package. It can reference:
    #: - any `pkg.Source` attribute (e.g. `pkg.Source.dir_name`).
    name = pilo.fields.String(default='{source.dir_name}')

    #: Format specification for the name of this package. It can reference:
    #: - any `pkg.Source` attribute (e.g. `pkg.Source.git_version`).
    version = pilo.fields.String(default='{source.git_version}')

    #: Default file include patterns (mimics GITIGNORE(5)).
    default_includes = pilo.fields.List(pilo.fields.String())

    @default_includes.default
    def default_includes(self):
        from confu import pkg

        return pkg.Package.default_patterns

    #: File include patterns (mimics GITIGNORE(5)).
    includes = pilo.fields.List(pilo.fields.String(), default=list)

    #: Format specification for the directory where package is built. It can
    #: reference:
    #: - any `pkg.Source` attribute (e.g. `pkg.Source.git_version`).
    #: - any `pkg.Package` attribute (e.g. `pkg.Package.name`).
    stage_dir = pilo.fields.String(default=os.path.join(
        tempfile.gettempdir(), 'confu', '{package.name}-{package.version}'
    ))

    #: Format specification for publish package bucket. It can reference:
    #: - ``profile``
    #: - ``region`
    bucket_format = pilo.fields.String(default='confu-pkg')


class Atlas(pilo.Form):

    #: Path to python package defining a collection of troposphere patterns (aka
    #: an atlas). Paths are expanded relative to file containing this setting.
    source_dir = pilo.fields.String(default=None)

    @source_dir.munge
    def source_dir(self, value):
        if not self.ctx.src_path.location:
            return value
        start = os.path.dirname(self.ctx.src_path.location)
        value = os.path.abspath(os.path.relpath(value, start))
        return value


profile = None

region = None

aws = AWS()

cfn = CFN()

pkg = PKG()

atlas = Atlas()


def locations():
    return filter(lambda path: os.path.exists(path), [
        os.path.expanduser('~/.confu.cfg'),
        os.path.join(os.getcwd(), '.confu.cfg'),
    ])


def load(profile=None, region=None, globalize=True, *paths):

    def _union(configs, name, profile):
        srcs = []
        name_profile = '{0} {1}'.format(name, profile) if profile else None
        for path, config in configs:
            if name_profile and config.has_section(name_profile):
                srcs.append(pilo.source.ConfigSource(
                    config,
                    section=name_profile,
                    location=path,
                    preserve_whitespace=True,
                ))
            if config.has_section(name):
                srcs.append(pilo.source.ConfigSource(
                    config,
                    section=name,
                    location=path,
                    preserve_whitespace=True,
                ))
        return pilo.source.UnionSource(srcs, merge='combine')

    # load config
    configs = []
    for path in locations() + list(paths):
        if not path:
            continue
        logger.debug('loading "%s"', path)
        config = ConfigParser.ConfigParser()
        config.optionxform = str  # NOTE: preserve case
        config.read(path)
        configs.append((path, config))

    # merge config
    default = Default(_union(configs, 'default', None))
    aws = AWS(_union(configs, 'aws', profile))
    cfn = CFN(_union(configs, 'cfn', profile))
    pkg = PKG(_union(configs, 'pkg', profile))
    atlas = Atlas(_union(configs, 'atlas', profile))

    # derive
    profile = profile or default.profile
    region = region or aws.default_region

    logger.info('settings -\n%s', json.dumps({
        'profile': profile,
        'region': region,
        'aws': aws,
        'cfn': cfn,
        'pkg': pkg,
        'atlas': atlas,
    }, indent=4))
    if globalize:
        # make it so
        globals().update(
            profile=profile,
            region=region,
            aws=aws,
            cfn=cfn,
            pkg=pkg,
            atlas=atlas,
        )
    return dict(
        profile=profile,
        region=region,
        aws=aws,
        cfn=cfn,
        pkg=pkg,
        atlas=atlas,
    )
