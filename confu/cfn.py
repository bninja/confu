"""
Manages AWS cloudformation templates and stacks as represented by:

- `cfn.Template` and
- `cfn.Stack`

using contextual information in:

- `cfn.Context`

and exposed like:

.. code:: bash

    $ confu cfn --help

"""
from collections import OrderedDict

import errno
import fnmatch
import hashlib
import logging
import json
import os
import random
import string
import subprocess
import sys
import threading
import time
import urllib2
import urlparse

import boto.s3.key
import click

from . import settings, cli, aws


logger = logging.getLogger(__name__)


class Context(threading.local):

    def __init__(self):
        self._bucket = None

    def reset(self):
        self._bucket = None

    def key_for(self, *names):
        return '/'.join([settings.cfn.bucket_key] + list(names))

    def url_for(self, key, auth=False):
        return aws.url_for_s3_key(key, auth=auth)

    @property
    def bucket(self):
        if self._bucket is None:
            name = settings.cfn.bucket_format.format(**{
                'profile': settings.profile,
                'region': settings.region,
            })
            self._bucket = aws.get_s3_bucket(
                name, region=settings.region, create=True)
        return self._bucket


ctx = Context()


class Template(object):

    @classmethod
    def from_url(cls, url):
        parsed = urlparse.urlparse(url, allow_fragments=False)
        if parsed.scheme in ('', 'file'):
            return Template.from_file(parsed.path)
        if parsed.scheme in ('http', 'https'):
            return Template.from_http(url)
        raise ValueError('Unsupported scheme "{0}"'.format(parsed.scheme))

    @classmethod
    def from_file(cls, path):
        if os.access(path, os.X_OK):
            template = TemplateScript(path)
        else:
            template = TemplateRendered(open(path, 'r').read())
        return template

    @classmethod
    def from_http(cls, url):
        resp = urllib2.urlopen(url)
        code = resp.getcode()
        if code not in (200,):
            raise Exception('GET "{0}" failed - {1}'.format(url, code))
        body = resp.read()
        return TemplateRendered(body)

    @property
    def body(self):
        raise NotImplementedError

    @property
    def name(self):
        return hashlib.sha1(str(self)).hexdigest().decode('utf-8') + '.json'

    @property
    def params(self):
        return self.body.get('Parameters', {})

    @property
    def required(self):
        return dict(
            (name, param)
            for name, param in self.params.iteritems()
            if 'Default' not in param
        )

    @property
    def defaults(self):
        return dict(
            (name, param)
            for name, param in self.params.iteritems()
            if 'Default' in param
        )

    def remote(self, auth=False):
        key = ctx.bucket.get_key(ctx.key_for(self.name))
        if key is None:
            raise Exception(
                'Not found @ s3://{bucket}/{key}!'
                .format(bucket=ctx.bucket.name, key=ctx.key_for(self.name))
            )
        return ctx.url_for(key, auth=auth)

    @property
    def has_remote(self):
        return ctx.bucket.get_key(ctx.key_for(self.name)) is not None

    def validate(self):
        if not self.has_remote:
            remote = self.upload()
        else:
            remote = self.remote()
        aws.cxn.cloudformation().validate_template(template_url=remote)

    def upload(self, auth=False):
        key = boto.s3.key.Key(ctx.bucket, ctx.key_for(self.name))
        key.set_contents_from_string(
            str(self), headers={'Content-Type': 'application/json'}
        )
        return ctx.url_for(key, auth=auth)

    def __str__(self):
        json_repr = self.body
        # follow AWSCloudFormation/latest/UserGuide/template-anatomy.html
        # to print out the template
        sorted_keys = [
            'AWSTemplateFormatVersion',
            'Description',
            'Parameters',
            'Mappings',
            'Conditions',
            'Resources',
            'Properties',
            'Function',
            'Outputs',
        ]

        def comparator(rhs, lhs):
            rhs_idx = sorted_keys.index(rhs)
            lhs_idx = sorted_keys.index(lhs)
            return -1 if rhs_idx < lhs_idx else lhs_idx

        t = OrderedDict(sorted(json_repr.items(),
                               key=lambda x: x[0],
                               cmp=comparator))

        return t.to_dict()

    def stack(self, name, params):
        return Stack.create(name, self, params)


class TemplateScript(Template):

    def __init__(self, script):
        super(TemplateScript, self).__init__()
        self.script = script
        self._body = None

    def render(self):
        if not os.path.isfile(self.script):
            raise Exception('"{0}" does not exist.'.format(self.script))
        if not os.access(self.script, os.X_OK):
            raise Exception('"{0}" is *not* executable.'.format(self.script))
        try:
            raw = subprocess.check_output(self.script, stderr=sys.stderr)
        except OSError, ex:
            if ex.errno == errno.ENOEXEC:
                logger.error(
                    '"%s" failed to execute, '
                    'are you missing "#!/usr/bin/env python"?',
                    self.script
                )
            raise
        try:
            return json.loads(raw)
        except ValueError:
            logger.error(
                '"%s" should print JSON template, got:\n"%s"',
                self.script, raw,
            )
            raise

    @property
    def body(self):
        if self._body is None:
            self._body = self.render()
        return self._body


class TemplateRendered(Template):

    def __init__(self, body):
        try:
            self._body = json.loads(body)
        except ValueError:
            logger.error('Expected JSON template, got:\n%s', body)
            raise

    @property
    def body(self):
        return self._body


class Stack(object):

    @classmethod
    def all(cls, *statuses):
        return map(
            cls.from_summary,
            aws.cxn.cloudformation().list_stacks(statuses or None)
        )

    @classmethod
    def from_resource(cls, resource):
        return cls(name=resource.tags['aws:cloudformation:stack-name'])

    @classmethod
    def from_summary(cls, summary):
        return cls(
            summary.stack_name,
            id=summary.stack_id,
            status=summary.stack_status,
        )

    @classmethod
    def create(cls, name, template, params):
        # expand stack outputs to params
        tmp = []
        for param in params:
            if len(param) == 1:
                for k, v in Stack(param[0]).outputs.iteritems():
                    if k in template.params:
                        tmp.append((k, v))
            else:
                tmp.append(param)
        params = tmp

        # format name
        name = name or settings.cfn.stack_name_format
        name_ctx = {
            'random': ''.join(
                random.choice(string.ascii_lowercase + string.digits)
                for _ in range(6)
            )
        }
        name_ctx.update(
            (name, param['Default'])
            for name, param in template.defaults.iteritems()
        )
        name_ctx.update(
            (name, value)
            for name, value in settings.cfn.parameters.iteritems()
        )
        name_ctx.update(params)
        logger.debug('"%s".format(%s)', name, name_ctx)
        name = name.format(**name_ctx)

        # validate params
        for key, _ in params:
            if key not in template.params:
                raise ValueError(
                    '"{0}" is not a parameter for {1} '.format(key, name)
                )

        # environment params
        for k, v in settings.cfn.parameters.iteritems():
            if k not in template.params:
                continue
            if any(key == k for key, _ in params):
                continue
            params.append((k, v.format(**{
                'profile': settings.profile,
                'region': settings.region,
            })))

        # create
        url = template.remote()
        tags = {
            'confu:source': 's3://{bucket}/{key}'.format(
                bucket=ctx.bucket.name, key=ctx.key_for(template.name)
            ),
        }
        tag_ctx = dict((name, value) for name, value in params)
        tags.update(
            ('confu:{0}'.format(name), value.format(tag_ctx))
            for name, value in settings.cfn.stack_tags.iteritems()
        )
        id = aws.cxn.cloudformation().create_stack(
            stack_name=name,
            template_url=url,
            parameters=params,
            tags=tags,
            capabilities=['CAPABILITY_IAM'],
        )
        return Stack(name, id=id)

    def __init__(self, name, id=None, status=None):
        self.name = name
        self._id = id
        self._status = status
        self._description = None

    def describe(self):
        if self._description is None:
            self._description = aws.cxn.cloudformation().describe_stacks(
                self.name
            )[0]
        return self._description

    def update(self, template, params):
        # expand stack outputs to params
        tmp = []
        for param in params:
            if len(param) == 1:
                for k, v in Stack(param[0]).outputs.iteritems():
                    if k in template.params:
                        tmp.append((k, v))
            else:
                tmp.append(param)
        params = tmp

        # validate params
        for key, _ in params:
            if key not in self.params:
                raise ValueError(
                    '"{0}" is not a parameter for {1} '.format(
                        key, template.name
                    )
                )

        # existing params
        for k, v in self.params.iteritems():
            if k not in template.params:
                continue
            if any(key == k for key, _ in params):
                continue
            params.append((k, v))

        # environment params
        for k, v in settings.cfn.parameters.iteritems():
            if k not in template.params:
                continue
            if any(key == k for key, _ in params):
                continue
            params.append((k, v.format(**{
                'profile': settings.profile,
                'region': settings.region,
            })))

        # update
        url = template.remote()
        tags = {
            'confu:source': 's3://{bucket}/{key}'.format(
                bucket=ctx.bucket.name, key=ctx.key_for(template.name)
            ),
        }
        tag_ctx = dict((name, value) for name, value in params)
        tags.update(
            ('confu:{0}'.format(name), value.format(tag_ctx))
            for name, value in settings.cfn.stack_tags.iteritems()
        )
        aws.cxn.cloudformation().update_stack(
            stack_name=self.name, template_url=url, parameters=params,
            tags=tags,
            capabilities=['CAPABILITY_IAM'],
        )

    def delete(self):
        logger.info('deleting stack %s', self.name)
        aws.cxn.cloudformation().delete_stack(self.name)

    @property
    def id(self):
        if self._id:
            return self._id
        return self.describe().stack_id

    @property
    def status(self):
        if self._status:
            return self._status
        return self.describe().stack_status

    @property
    def is_deleted(self):
        return self.status == 'DELETE_COMPLETE'

    def in_progress(self, desired):
        return self.status == '{0}_IN_PROGRESS'.format(
            desired.partition('_')[0]
        )

    @property
    def params(self):
        return dict(
            (param.key, param.value)
            for param in self.describe().parameters
        )

    @property
    def tags(self):
        return self.describe().tags

    @property
    def outputs(self):
        return dict(
            (output.key, output.value) for output in self.describe().outputs
        )

    def reset(self):
        self._description = None
        self._id = None
        self._status = None

    @property
    def template(self):
        body = aws.cxn.cloudformation().get_template(self.name)
        return TemplateRendered(body)


# cli.cfn

@cli.group('cfn')
def cfn():
    pass


@cfn.command('validate')
@click.argument('template_url')
def validate(template_url):
    template = Template.from_url(template_url)
    template.validate()


@cfn.command('render')
@click.argument('template_url')
def render(template_url):
    template = Template.from_url(template_url)
    print str(template)


@cfn.command('params')
@click.argument('template_url')
def parameters(template_url):
    template = Template.from_url(template_url)
    print json.dumps(template.params, indent=4, sort_keys=True)


@cfn.command('defaults')
@click.argument('template_url')
def defaults(template_url):
    template = Template.from_url(template_url)
    print json.dumps(template.defaults, indent=4, sort_keys=True)


@cfn.command('required')
@click.argument('template_url')
def required(template_url):
    template = Template.from_url(template_url)
    print json.dumps(template.required, indent=4, sort_keys=True)


@cfn.command('upload')
@click.argument('template_url')
@click.option('--auth/--no-auth', default=False)
def upload(template_url, auth):
    template = Template.from_url(template_url)
    print template.upload(auth=auth)


@cfn.command('uploaded')
@click.argument('template_url')
@click.option('--auth/--no-auth', default=False)
def uploaded(template_url, auth):
    print Template.from_url(template_url).remote(auth=auth)


@cfn.command('create')
@click.argument('template_url')
@click.argument('param', nargs=-1)
@click.option('-n', '--stack-name')
def create(template_url, param, stack_name):
    params = [tuple(param.split('=')) for param in param]
    template = Template.from_url(template_url)
    if not template.has_remote:
        template.upload()
    print template.stack(name=stack_name, params=params).name


@cfn.command('show')
@click.argument('stack_name')
@click.option('--deleted/--no-deleted', default=False)
def show(stack_name, deleted):

    def _summarize(stack):
        summary = {
            'name': stack.name,
            'id': stack.id,
            'status': stack.status,
        }
        if not stack.is_deleted:
            summary.update(
                params=stack.params,
                outputs=stack.outputs,
                tags=stack.tags,
            )
        return summary

    if any(c in stack_name for c in '%?*'):
        summary = []
        for stack in Stack.all():
            if not deleted and stack.is_deleted:
                continue
            if not fnmatch.fnmatch(stack.name, stack_name):
                continue
            summary.append(_summarize(stack))
    else:
        stack = Stack(stack_name)
        summary = _summarize(stack)
    print json.dumps(summary, indent=4, sort_keys=True)


@cfn.command('wait-for')
@click.argument('stack_name')
@click.argument('status', type=click.Choice(['created', 'deleted', 'updated']))
@click.option('--poll', type=int, default=1)
@click.option('-t', '--timeout', type=int, default=None)
@click.pass_context
def wait_for(ctx, stack_name, status, poll, timeout):
    stack = Stack(stack_name)
    desired = {
        'created': 'CREATE_COMPLETE',
        'deleted': 'DELETE_COMPLETE',
        'updated': 'UPDATE_COMPLETE',
    }[status]
    if timeout:
        timeout = time.time() + timeout
    while True:
        if stack.status == desired:
            break
        if not stack.in_progress(desired):
            raise Exception(
                'Bailing on {0} with status {1}'.format(
                    stack.name, stack.status
                )
            )
        if timeout and time.time() > timeout:
            raise Exception(
                'Timeout on {0} with status {1}'.format(
                    stack.name, stack.status
                )
            )
        time.sleep(poll)
        stack = Stack(stack_name)
    ctx.invoke(show, stack.name)


@cfn.command('delete')
@click.argument('stack_names', nargs=-1)
def delete(stack_names):
    for stack_name in stack_names:
        if any(c in stack_name for c in '%?*'):
            for stack in Stack.all():
                if stack.is_deleted:
                    continue
                if not fnmatch.fnmatch(stack.name, stack_name):
                    continue
                stack.delete()
        else:
            Stack(stack_name).delete()


@cfn.command('update')
@click.argument('stack_name')
@click.argument('template_url')
@click.argument('param', nargs=-1)
def update(stack_name, template_url, param):
    params = [tuple(param.split('=')) for param in param]
    template = Template.from_url(template_url)
    if not template.has_remote:
        template.upload()
    Stack(stack_name).update(template=template, params=params)
