import os

from middlewared.schema import Bool, Dict, Str
from middlewared.service import accepts, CallError, Service

from .utils import get_namespace, run


class ChartReleaseService(Service):

    class Config:
        namespace = 'chart.release'

    @accepts(
        Str('release_name'),
        Dict(
            'rollback_options',
            Bool('force', default=False),
            Str('item_version', required=True),
        )
    )
    async def rollback(self, release_name, options):
        release = await self.middleware.call(
            'chart.release.query', [['id', '=', release_name]], {
                'extra': {'history': True, 'retrieve_resources': True}, 'get': True,
            }
        )
        rollback_version = options['item_version']
        if rollback_version not in release['history']:
            raise CallError(f'Unable to find {rollback_version!r} item version in {release_name!r} history')

        chart_path = os.path.join(release['path'], 'charts', rollback_version)
        if not await self.middleware.run_in_thread(lambda: os.path.exists(chart_path)):
            raise CallError(f'Unable to locate {chart_path!r} path for rolling back')

        snap_name = f'{os.path.join(release["dataset"], "volumes/ix_volumes")}@{rollback_version}'
        if not await self.middleware.call('zfs.snapshot.query', [['id', '=', snap_name]]) and not options['force']:
            raise CallError(f'Unable to locate {snap_name!r} snapshot for {release_name!r} volumes')

        history_ver = str(release['history'][rollback_version]['version'])
        # TODO: Upstream helm does not have ability to force stop a release, until we have that ability
        #  let's just try to do a best effort to scale down scaleable workloads and then scale them back up

        scale_stats = await self.middleware.call('chart.release.scale', release_name, {'replica_count': 0})

        command = []
        if options['force']:
            command.append('--force')

        cp = await run(
            [
                'helm', 'rollback', release_name, history_ver, '-n',
                get_namespace(release_name), '--recreate-pods'
            ] + command, check=False,
        )
        if cp.returncode:
            raise CallError(
                f'Failed to rollback {release_name!r} chart release to {rollback_version!r}: {cp.stderr.decode()}'
            )

        await self.middleware.call(
            'zfs.snapshot.rollback', snap_name, {
                'force': options['force'],
                'recursive': True,
                'recursive_clones': True,
            }
        )

        await self.middleware.call(
            'chart.release.scale_release_internal', release['resources'], None, scale_stats['before_scale']
        )

        return await self.middleware.call('chart.release.get_instance', release_name)
