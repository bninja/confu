"""
Ansible helpers for:

- `dynamic inventories <http://docs.ansible.com/developing_inventory.html>`_
- `lookup plugins <http://docs.ansible.com/developing_plugins.html#lookup-plugins>`_

"""
from __future__ import absolute_import

import collections
import json

import boto.provider
import boto.s3
import click
import yaml

from . import logging_at, aws


__all__ = [
    'AWSLocalInventory',
    'AWSRemoteInventory',
    'S3LookupModule',
    'CitadelLookupModule',
]


class Inventory(object):

    def all(self):
        """
        Returns groups formatted as:

            http://docs.ansible.com/developing_inventory.html

        says.
        """
        raise NotImplementedError

    def one(self, host):
        """
        Returns variables for single host as:

            http://docs.ansible.com/developing_inventory.html

        says.
        """
        raise NotImplementedError

    @property
    def cli(self):
        """
        Creates a:

            http://docs.ansible.com/developing_inventory.html

        compliant command line interface for this inventory, e.g.:

        .. code:: python

            #!/usr/bin/env python

            if __name__ == '__main__':
                inventory.cli()

        See --help for details.
        """
        raise NotImplementedError


class AWSInventory(Inventory):

    def __init__(self, instances, account_alias=None, group_tags=None):
        super(AWSInventory, self).__init__()
        self.instances = instances
        self.account_alias = (
            account_alias or
            # TODO: no aws.cxn.iam().get_account_alias()[0]?
            aws.cxn.iam().get_account_alias()['list_account_aliases_response']['list_account_aliases_result']['account_aliases'][0]
        )
        self.group_tags = []
        for group_tag in group_tags:
            self.group_tag(group_tag)

    def host_for(self, instance):
        raise NotImplementedError

    def instance_for(self, host):
        raise NotImplementedError

    def host_vars(self, instance):
        raise NotImplementedError

    def group_tag(self, tag):
        name, munge, var = None, None, None
        if isinstance(tag, basestring):
            name = tag
        elif isinstance(tag, (tuple, list)):
            if not 1 <= len(tag) <= 3:
                raise TypeError(
                    'Tag "{0}" must be (name[, munge][, var])'.format(tag)
                )
            name = tag[0]
            if len(tag) > 1:
                munge = tag[1]
                if isinstance(munge, basestring):
                    spec = munge
                    munge = lambda x: spec.format(value=x)
            if len(tag) > 2:
                var = tag[2]
        else:
            raise TypeError('Tag "{0}" ist not a string or tuple'.format(tag))
        self.group_tags.append((name, munge, var))

    # Inventory

    def all(self):
        groups = collections.defaultdict(
            lambda: dict(hosts=set(), children=set(), vars=dict())
        )

        groups[self.account_alias]['vars']['aws_account'] = self.account_alias

        host_vars = {}
        for instance in self.instances:
            host = self.host_for(instance)
            vars_ = self.host_vars(instance)
            if vars_:
                host_vars[host] = vars_

            # account
            groups[self.account_alias]['children'].add(instance.region.name)
            groups[self.account_alias]['hosts'].add(host)

            # region
            groups[instance.region.name]['hosts'].add(host)
            groups[instance.region.name]['vars']['aws_region'] = (
                instance.region.name
            )

            # region placement
            groups[instance.region.name]['children'].add(instance.placement)
            groups[instance.placement]['hosts'].add(host)
            groups[instance.placement]['vars']['aws_placement'] = instance.placement

            # tagged
            for name, munge, var in self.group_tags:
                if name not in instance.tags:
                    continue
                group_name = value = instance.tags[name]
                if munge:
                    group_name = munge(group_name)
                if isinstance(group_name, basestring):
                    group_names = [group_name]
                elif isinstance(group_names, list):
                    group_names = group_name
                else:
                    raise TypeError(
                        'Tag "{0}" munge must return string or strings'
                    )
                for group_name in group_names:
                    groups[group_name]['hosts'].add(host)
                    if var:
                        groups[group_name]['vars'][var] = value

        result = {}

        for name, group in groups.iteritems():
            if group['hosts']:
                group['hosts'] = list(group['hosts'])
            else:
                group.pop('hosts', None)
            if group['children']:
                group['children'] = list(group['children'])
            else:
                group.pop('children', None)
            if not group['vars']:
                group.pop('vars', None)
            if group.get('hosts') or group.get('children'):
                result[name] = dict(group)

        result['_meta'] = {
            'hostvars': host_vars
        }

        return result

    def one(self, host):
        instance = self.instance_for(host)
        return self.host_vars(instance) or {}


class AWSLocalInventory(AWSInventory):
    """
    Dynamic inventory for this AWS host, e.g.:

    .. code:: python

        #!/usr/bin/env python

        from confu.ansible import AWSLocalInventory

        inventory = AWSLocalInventory(
            group_tags=[
               'aws:cloudformation:stack-name',
               ('confu:infra-env', 'env-{value}')
               ('confu:app-env', 'env-{value}')
            ],
            group_filters=[
                'julius',
            ]
        )

        if __name__ == '__main__':
            inventory.cli()

    """

    def __init__(self, account_alias=None, group_tags=None):
        super(AWSLocalInventory, self).__init__(
            instances=[aws.this_instance()],
            account_alias=account_alias,
            group_tags=group_tags,
        )

    # AWSInventory

    def host_for(self, instance):
        return '127.0.0.1'

    def instance_for(self, host):
        if '127.0.0.1' == host:
            return self.instances[0]
        raise LookupError('No instances for host "{0}"'.format(host))

    def host_vars(self, instance, default=None):
        return default

    # Inventory

    @property
    def cli(self):

        @click.command()
        @click.option('--list', is_flag=True)
        @click.option('--host', metavar='<hostname>', nargs=1, default=None)
        @click.option('-l', '--log-level', type=click.Choice(['d', 'i', 'w', 'e']), default='e')
        def _cli(list, host, log_level):
            logging_at(log_level)
            if host is not None:
                result = self.one(host)
            else:
                result = self.all()
            print json.dumps(result, indent=4, sort_keys=True)

        return _cli


class AWSRemoteInventory(AWSInventory):
    """
    Dynamic inventory for remote AWS host(s), e.g.:

    .. code:: python

        #!/usr/bin/env python

        from confu.ansible import AWSRemoteInventory

        inventory = AWSRemoteInventory(
            'julius',
            instances=(
                aws.instances()
                .regions('us-west-1')
                .filter(('tag:confu:infra', 'julius'))
            ),
            group_tags=[
               'aws:cloudformation:stack-name',
               ('confu:infra-env', 'env-{value}', 'infra_env')
               ('confu:app-env', 'env-{value}', 'app_env')
            ],
        )

        if __name__ == '__main__':
            inventory.cli()

    """

    def __init__(
            self,
            instances,
            account_alias=None,
            group_tags=None,
            vars_metadata_key=None,
            vars_metadata_type=None):
        super(AWSRemoteInventory, self).__init__(
            instances,
            account_alias=account_alias,
            group_tags=group_tags,
        )
        self.vars_metadata_key = vars_metadata_key
        self.vars_metadata_type = vars_metadata_type

    def filter(self, *regions):
        self.instances = self.instances.regions(*regions)

    vars_metadata_types = {
        'application/json': json.loads,
        'application/x-yaml': yaml.load,
    }

    # AWSLocalInventory

    def host_for(self, instance):
        return instance.ip_address or instance.private_ip_address

    def instance_for(self, host):
        instances = list(self.instances.filter(('private_ip_address', host)))
        if not instances:
            instances = list(self.instances.filter(('ip_address', host)))
            if not instances:
                raise LookupError('No instances for host "{0}"'.format(host))
        if len(instances) > 1:
            raise Exception('Multiple instances for host "{0}"'.format(host))
        return instances[0]

    def host_vars(self, instance, default=None):
        if not aws.is_stack_resource(instance):
            return default
        host = self.host_for(instance)
        md = aws.retry()(aws.stack_resource_metadata, instance, None)
        if md is None:
            return default
        vars_ = md
        if self.vars_metadata_key:
            for k in self.vars_metadata_key:
                if k not in vars_:
                    return default
                vars_ = vars_[k]
        if isinstance(vars_, basestring):
            text_vars = vars_
            if self.vars_metadata_type not in self.vars_metadata_types:
                raise ValueError(
                    'vars_metadata_type="{0}" not supported.'
                    .format(self.vars_metadata_type)
                )
            vars_ = self.vars_metadata_types[self.vars_metadata_type](
                text_vars
            )
            if not isinstance(vars_, dict):
                raise TypeError(
                    'Host "{0}" metadata @ {1}\n{2}\n is not a "{3}" mapping.'
                    .format(
                        host,
                        self.vars_metadata_key,
                        text_vars,
                        self.vars_metadata_type
                    )
                )
        elif not isinstance(vars_, dict):
            raise TypeError(
                'Host "{0}" metadata @ {1} not a mapping.'.format(host)
            )
        if instance.private_ip_address:
            vars_['private_ip_address'] = instance.private_ip_address
        return vars_

    # Inventory

    @property
    def cli(self):

        @click.command()
        @click.option('--list', is_flag=True)
        @click.option('--host', metavar='<hostname>', nargs=1, default=None)
        @click.option('--no-cache', is_flag=True, help='Do not cache.')
        @click.option('--bust', is_flag=True, help='Bust cache first.')
        @click.option('-r', '--regions', type=click.Choice(['us-west-1', 'us-west-2', 'us-east-1']), multiple=True)
        @click.option('-l', '--log-level', type=click.Choice(['d', 'i', 'w', 'e']), default='e')
        def _cli(list, host, no_cache, bust, regions, log_level):
            # TODO: caching w/ no_cache, bust awareness
            logging_at(log_level)
            if regions:
                self.filter(*regions)
            if host is not None:
                result = self.one(host)
            else:
                result = self.all()
            print json.dumps(result, indent=4, sort_keys=True)

        return _cli


class S3LookupModule(object):
    """
    Use it like:

    .. code:: python

        import confu

        class LookupModule(confu.ansible.S3LookupModule):

            bucket_var = 'citadel_bucket'

            profile_var = 'citadel_profile'

            region_var = 'citadel_region'

    and then load variable content from s3 in ansible like:

    .. code:: yaml

        newrelic_license_key: "{{ lookup('citadel', '/newrelic/license_key').strip() }}"

    """

    #: Default bucket. Override with "bucket=".
    bucket = None

    #: Variable name with default bucket.
    bucket_var = None

    #: Default connection profile. Override with "profile=".
    profile = None

    #: Variable name with default connection profile.
    profile_var = None

    #: Default connection region. Override with "region=".
    region = None

    #: Variable name with default connection region.
    region_var = None

    #: Object satisfying `collections.MutableMapping` or None for no caching.
    cache = None

    def cache_key(self, bucket_name, key_name):
        return 's3://{0}{1}'.format(bucket_name, key_name)

    def loads(self, content_type, content):
        return content

    def options(self, inject):
        options = {
            'bucket': self.bucket,
            'profile': self.profile,
            'region': self.region,
        }
        if inject:
            for option, var in [
                    ('bucket', self.bucket_var),
                    ('profile', self.profile_var),
                    ('region', self.region_var),
                ]:
                if var and var in inject:
                    options[option] = inject[var]
        return options

    # LookupModule

    def __init__(self, basedir=None, **kwargs):
        self.basedir = basedir

    def run(self, terms, inject=None, **kwargs):
        # XXX: messes with logging
        import ansible.utils

        # XXX: https://github.com/ansible/ansible/issues/7370

        terms = ansible.utils.listify_lookup_plugin_terms(terms, self.basedir, inject)

        ret = []

        defaults = self.options(inject)

        for term in terms:
            params = term.split()

            key_name = params[0]

            options = defaults.copy()
            try:
                for param in params[1:]:
                    name, value = param.split('=')
                    assert(name in options)
                    options[name] = value
            except (ValueError, AssertionError), e:
                raise ansible.errors.AnsibleError(e)

            # cache
            if self.cache is not None:
                cache_key = self.cache_key(options['bucket'], key_name)
                if cache_key in self.cache:
                    contents = self.cache[cache_key]
                    ret.append(contents)
                    continue

            # connect
            profile_name = options['profile']
            cxn = None
            while cxn is None:
                try:
                    if options['region']:
                        cxn = boto.s3.connect_to_region(
                            options['region'], profile_name=profile_name,
                        )
                    else:
                        cxn = boto.connect_s3(profile_name=profile_name)
                except boto.provider.ProfileNotFoundError, e:
                    if profile_name is None:
                        raise ansible.errors.AnsibleError('Unable to connect to s3')
                    profile_name = None
                except (boto.exception.BotoClientError, boto.exception.S3ResponseError), e:
                    raise ansible.errors.AnsibleError('Unable to connect to s3')

            # read
            # NOTE: lookup deferred (validate=False) so we don't need s3:List* permission
            bucket = cxn.get_bucket(options['bucket'], validate=False)
            key = boto.s3.key.Key(bucket, key_name)
            try:
                contents = key.get_contents_as_string()
            except boto.exception.S3ResponseError, e:
                raise ansible.errors.AnsibleError(
                    'Unable to get s3://{bucket}/{key} contents - {code}, {message}'.format(
                        bucket=options['bucket'],
                        key=key_name,
                        code=e.error_code,
                        message=e.message,
                    )
                )

            # cache
            if self.cache is not None:
                cache_key = self.cache_key(options['bucket'], key_name)
                self.cache[cache_key] = contents

            ret.append(contents)

        return ret
