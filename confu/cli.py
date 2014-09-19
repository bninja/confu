import os

import click

from . import settings, aws, logging_at


@click.group()
@click.option('-c', '--cfg', type=click.File())
@click.option('-l', '--log-level', type=click.Choice(['d', 'i', 'w']), default=os.environ.get('CONFU_LOG') or 'w')
@click.option('-p', '--profile', default=os.environ.get('CONFU_PROFILE') or None)
@click.option('-r', '--region', type=click.Choice(aws.region_names()), default=os.environ.get('CONFU_REGION') or None)
def cli(cfg, log_level, profile, region):
    logging_at(log_level)
    settings.load(
        profile=profile,
        region=region,
        *([cfg] if cfg is not None else [])
    )
    aws.cxn.activate(
        profile_name=settings.profile,
        default_region=settings.region,
    )
