import collections
import datetime
import json
import threading
import time

import boto.cloudformation
import boto.iam
import boto.ec2
import boto.s3


def region_names(service='ec2'):
    return [region.name for region in boto.regioninfo.get_regions(service)]


class Connection(threading.local):
    """
    Global per-thread connection map. Typically used via singleton like this:

    .. code: python

        cxn.activate(profile_name='my-profile')

    or, if you don't control the context, like this:

    .. code: python

        with cxn.activate(profile_name='my-profile'):
            pass

    so that subsequent code can just do:

    .. code: python

        s3 = aws.cxn.s3('us-west-1')

    to re-use commonly authenticated connections.
    """

    def __init__(self):
        self.reset()

    def activate(self,
                 access_key=None,
                 secret_key=None,
                 security_token=None,
                 profile_name=None,
                 default_region=None,
        ):
        self.reset()
        self.default_region = default_region
        self.creds = {
            'aws_access_key_id': access_key,
            'aws_secret_access_key': secret_key,
            'security_token': security_token,
            'profile_name': profile_name,
        }

    def reset(self):
        self.default_region = None
        self.creds = {
            'aws_access_key_id': None,
            'aws_secret_access_key': None,
            'security_token': None,
            'profile_name': None,
        }
        self._cloudformation = {}
        self._ec2 = {}
        self._s3 = {}
        self._iam = {}

    def s3(self, region=None):
        return self._connect(region, boto.s3, self._s3)

    def iam(self, region=None):
        return self._connect(region, boto.iam, self._iam)

    def cloudformation(self, region=None):
        return self._connect(region, boto.cloudformation, self._cloudformation)

    def ec2(self, region=None):
        return self._connect(region, boto.ec2, self._ec2)

    def _connect(self, region, service, cache):
        if region is None:
            if self.default_region is None:
                raise ValueError('No default_region yet region=None')
            if self.default_region == 'this':
                identity = boto.utils.get_instance_identity()
                self.default_region = identity['document']['region']
            region = self.default_region
        if region not in cache:
            cxn = service.connect_to_region(region_name=region, **self.creds)
            cache[region] = cxn
        return cache[region]


#: Singleton global per-thread connection map.
cxn = Connection()


class instances(collections.Sequence):
    """
    A sequence of filtered instances, e.g.:

    .. code:: python

        print list(
            instances()
            .regions('us-west-1')
            .filter(('tag:confu:infra', 'fical'))
        )

    """

    def __init__(self, regions=None, filters=None):
        self._regions = regions or []
        self._filters = filters or []
        self._instances = None

    def regions(self, *regions):
        return type(self)(regions, self._filters)

    def filter(self, *filters):
        return type(self)(self._regions, self._filters + list(filters))

    def __getitem__(self, key):
        return self.all()[key]

    def __len__(self):
        return self.len(self.all())

    def all(self):
        if self._instances is None:
            instances = []
            for region_name in self._regions:
                ec2 = cxn.ec2(region_name)
                for instance in ec2.get_only_instances(filters=self._filters):
                    instances.append(instance)
            self._instances = instances
        return self._instances


def this_instance():
    identity = boto.utils.get_instance_identity()
    region_name = identity['document']['region']
    instance_id = identity['document']['instanceId']
    instances = cxn.ec2(region=region_name).get_only_instances(
        instance_ids=[instance_id]
    )
    if not instances:
        raise Exception(
            'No instance with id {0} in region {1}'
            .format(identity['instanceId'], identity['region'])
        )
    return instances[0]


def this_region():
    identity = boto.utils.get_instance_identity()
    region_name = identity['document']['region']
    return region_name


def get_s3_bucket(name, region=None, create=False):
    try:
        return cxn.s3(region).get_bucket(name)
    except boto.exception.S3ResponseError:
        return cxn.s3(region).create_bucket(
            name,
            location={
                'us-west-1': boto.s3.connection.Location.USWest,
                'us-west-2': boto.s3.connection.Location.USWest2,
                'us-east-1': boto.s3.connection.Location.DEFAULT,
                'eu-west-1': boto.s3.connection.Location.EU,
            }[region],
            policy='private',
        )


def url_for_s3_key(key, auth=False):
    if auth:
        return key.generate_url(
            expires_in=datetime.timedelta(days=1).total_seconds()
        )
    return 'https://{host}/{bucket}/{key}'.format(
        host=cxn.s3().server_name(),
        bucket=key.bucket.name,
        key=key.name,
    )


def is_stack_resource(resource):
    return (
        'aws:cloudformation:stack-name' in resource.tags and
        'aws:cloudformation:logical-id' in resource.tags
    )


def describe_stack_resource(resource):
    return cxn.cloudformation().describe_stack_resource(
        resource.tags['aws:cloudformation:stack-name'],
        resource.tags['aws:cloudformation:logical-id']
    )


def stack_resource_metadata(resource, *args):
    result = (
        describe_stack_resource(resource)
        ['DescribeStackResourceResponse']
        ['DescribeStackResourceResult']
        ['StackResourceDetail']
    )
    v = result.get('Metadata', *args)
    if isinstance(v, basestring):
        v = json.loads(result['Metadata'])
    return v


def retry(sleep=1, max_sleep=60, max_count=10):
    """
    https://github.com/ansible/ansible-modules-core/blob/7fb0605824df897548e5cd3fd00789365c8f20df/cloud/amazon/ec2_elb_lb.py#L404
    """

    def _loop(func, *args, **kwargs):
        count = 0
        while True:
            try:
                return func(*args, **kwargs)
            except boto.exception.BotoServerError, ex:
                if ex.code != 'Throttling' or count == max_count:
                    raise
                cur_sleep = min(max_sleep, sleep * (2 ** count))
                time.sleep(cur_sleep)
                count += 1

    return _loop
