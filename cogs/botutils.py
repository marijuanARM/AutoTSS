from datetime import datetime
from discord.enums import SlashCommandOptionType
from discord.ext import commands
from utils.device import Device
from utils.errors import *
from typing import Optional, Union

import aiofiles
import aiopath
import asyncio
import discord
import glob
import ujson
import pathlib
import remotezip
import shutil
import sys


API_URL = 'https://api.ipsw.me/v4'
BETA_API_URL = 'https://api.m1sta.xyz/betas'


class UtilsCog(commands.Cog, name='Utilities'):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.saving_blobs = False

    READABLE_INPUT_TYPES = {
        discord.TextChannel: 'channel',
        SlashCommandOptionType.string: 'string',
        SlashCommandOptionType.channel: 'channel',
        SlashCommandOptionType.user: 'user',
    }

    async def get_tsschecker_version(self) -> str:
        args = (
            'tsschecker'
            if sys.platform != 'win32'
            else next(
                b
                async for b in aiopath.AsyncPath(__file__).parent.glob(
                    'tsschecker*.exe'
                )
                if await b.is_file()
            ),
            '-h',
        )

        cmd = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE
        )
        stdout = (await cmd.communicate())[0]

        return stdout.decode().splitlines()[0].split(': ')[-1]

    async def get_uptime(self, time: datetime) -> str:
        return discord.utils.format_dt(time, style='R')

    async def get_whitelist(
        self, guild: int
    ) -> Optional[Union[bool, discord.TextChannel]]:
        async with self.bot.db.execute(
            'SELECT * FROM whitelist WHERE guild = ?', (guild,)
        ) as cursor:
            data = await cursor.fetchone()

        if (data is None) or (data[2] == False):
            return None

        try:
            return await self.bot.fetch_channel(data[1])
        except discord.errors.NotFound:
            await self.bot.db.execute('DELETE FROM whitelist WHERE guild = ?', (guild,))
            await self.bot.db.commit()

    @property
    def invite(self) -> str:
        return discord.utils.oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(93184),
            scopes=('bot', 'applications.commands'),
        )

    def shsh_count(self, ecid: str = None) -> int:
        if ecid:
            shsh_count = len(
                [
                    blob
                    for blob in glob.glob(
                        str(pathlib.Path(f'Data/Blobs/{ecid}/**/*.shsh*')),
                        recursive=True,
                    )
                ]
            )
        else:
            shsh_count = len(
                [
                    blob
                    for blob in glob.glob(
                        str(pathlib.Path('Data/Blobs/**/*.shsh*')), recursive=True
                    )
                ]
            )

        return shsh_count

    async def update_device_count(self) -> None:
        async with self.bot.db.execute(
            'SELECT devices from autotss WHERE enabled = ?', (True,)
        ) as cursor:
            num_devices = sum(
                len(ujson.loads(devices[0])) for devices in await cursor.fetchall()
            )

        await self.bot.change_presence(
            activity=discord.Game(
                name=f"Saving SHSH blobs for {num_devices} device{'s' if num_devices != 1 else ''}."
            )
        )

    async def whitelist_check(self, ctx: discord.ApplicationContext) -> None:
        if await self.bot.is_owner(ctx.author) or (
            isinstance(ctx.author, discord.Member)
            and ctx.author.guild_permissions.manage_messages
        ):
            return

        whitelist = await self.get_whitelist(ctx.guild.id)
        if whitelist is None:
            return

        if whitelist.id != ctx.channel.id:
            raise NotWhitelisted(whitelist)

    # Help embed functions
    def cmd_help_embed(
        self, ctx: discord.ApplicationContext, cmd: discord.SlashCommand
    ):
        embed = {
            'title': f"/{' '.join((cmd.full_parent_name, cmd.name)) or cmd.name} ",
            'description': cmd.description,
            'fields': list(),
            'footer': {
                'text': ctx.author.display_name,
                'icon_url': str(
                    ctx.author.display_avatar.with_static_format('png').url
                ),
            },
        }

        for arg in cmd.options:
            embed['title'] += f'<{arg.name}> ' if arg.required else f'[{arg.name}] '
            embed['fields'].append(
                {
                    'name': f'<{arg.name}>' if arg.required else f'[{arg.name}]',
                    'value': f"```Description: {arg.description or 'No description'}\nInput Type: {self.READABLE_INPUT_TYPES[arg.input_type]}\nRequired: {arg.required}```",
                    'inline': True,
                }
            )

        return discord.Embed.from_dict(embed)

    def cog_help_embed(
        self, ctx: discord.ApplicationContext, cog: str
    ) -> list[discord.Embed]:
        embed = {
            'title': f"{cog.capitalize() if cog != 'tss' else cog.upper()} Commands",
            'fields': list(),
            'footer': {
                'text': ctx.author.display_name,
                'icon_url': str(
                    ctx.author.display_avatar.with_static_format('png').url
                ),
            },
        }

        for cmd in self.bot.cogs[cog].get_commands():
            if isinstance(cmd, discord.SlashCommandGroup):
                continue

            cmd_field = {
                'name': f"/{cmd.name} ",
                'value': cmd.description,
                'inline': False,
            }

            for arg in cmd.options:
                cmd_field['name'] += (
                    f'<{arg.name}> ' if arg.required else f'[{arg.name}] '
                )

            embed['fields'].append(cmd_field)

        embed['fields'] = sorted(embed['fields'], key=lambda field: field['name'])
        return discord.Embed.from_dict(embed)

    def group_help_embed(
        self, ctx: discord.ApplicationContext, group: discord.SlashCommandGroup
    ) -> list[discord.Embed]:
        embed = {
            'title': f"{group.name.capitalize() if group.name != 'tss' else group.name.upper()} Commands",
            'fields': list(),
            'footer': {
                'text': ctx.author.display_name,
                'icon_url': str(
                    ctx.author.display_avatar.with_static_format('png').url
                ),
            },
        }

        for cmd in group.subcommands:
            cmd_field = {
                'name': f"/{' '.join((group.name, cmd.name))} ",
                'value': cmd.description,
                'inline': False,
            }
            for arg in cmd.options:
                cmd_field['name'] += (
                    f'<{arg.name}> ' if arg.required else f'[{arg.name}] '
                )

            embed['fields'].append(cmd_field)

        embed['fields'] = sorted(embed['fields'], key=lambda field: field['name'])
        return discord.Embed.from_dict(embed)

    def info_embed(self, member: discord.Member) -> discord.Embed:
        notes = (
            f"There is a limit of **{self.bot.max_devices} device{'s' if self.bot.max_devices != 1 else ''} per user**.",
            "You **must** share a server with AutoTSS, or else **AutoTSS won't automatically save SHSH blobs for you**.",
            'AutoTSS checks for new versions to save SHSH blobs for **every 5 minutes**.',
        )

        embed = {
            'title': "Hey, I'm AutoTSS!",
            'thumbnail': {
                'url': str(self.bot.user.display_avatar.with_static_format('png').url)
            },
            'fields': [
                {
                    'name': 'What do I do?',
                    'value': 'I can automatically save SHSH blobs for all of your iOS devices!',
                    'inline': False,
                },
                {
                    'name': 'What are SHSH blobs?',
                    'value': 'A great explanation that takes an in-depth look at what SHSH blobs are, what they can be used for, and more can be found [here](https://www.reddit.com/r/jailbreak/comments/m3744k/tutorial_shsh_generatorbootnonce_apnonce_nonce/).',
                    'inline': False,
                },
                {
                    'name': 'Disclaimer',
                    'value': 'I am not at fault for any issues you may experience with AutoTSS.',
                    'inline': False,
                },
                {
                    'name': 'Support',
                    'value': 'For AutoTSS support, join my [Discord](https://m1sta.xyz/discord).',
                    'inline': False,
                },
                {'name': 'All Commands', 'value': '`/help`', 'inline': True},
                {'name': 'Add Device', 'value': '`/devices add`', 'inline': True},
                {'name': 'Save SHSH Blobs', 'value': '`/tss save`', 'inline': True},
                {'name': 'Notes', 'value': '- ' + '\n- '.join(notes), 'inline': False},
            ],
            'footer': {
                'text': member.display_name,
                'icon_url': str(member.display_avatar.with_static_format('png').url),
            },
        }

        return discord.Embed.from_dict(embed)

    # SHSH Blob functions
    async def _get_manifest(
        self, url: str, path: str
    ) -> Union[bool, aiopath.AsyncPath]:
        async with self.bot.session.get(
            f"{'/'.join(url.split('/')[:-1])}/BuildManifest.plist"
        ) as resp:
            if resp.status == 200:
                manifest = await resp.read()
            else:
                return False

        manifest_path = pathlib.Path(path) / 'manifest.plist'
        with manifest_path.open('wb') as f:
            f.write(manifest)

        return aiopath.AsyncPath(manifest_path)

    def _sync_get_manifest(self, url: str, path: str) -> Union[bool, aiopath.AsyncPath]:
        try:
            with remotezip.RemoteZip(url) as ipsw:
                manifest = ipsw.read(
                    next(f for f in ipsw.namelist() if 'BuildManifest' in f)
                )
        except (remotezip.RemoteIOError, StopIteration):
            return False

        manifest_path = pathlib.Path(path) / 'manifest.plist'
        with manifest_path.open('wb') as f:
            f.write(manifest)

        return aiopath.AsyncPath(manifest_path)

    async def _save_blob(
        self, device: Device, firm: dict, manifest: str, tmpdir: aiopath.AsyncPath
    ) -> bool:
        generators = list()
        save_path = ['Data', 'Blobs', device.ecid, firm['version'], firm['buildid']]

        args = [
            'tsschecker'
            if sys.platform != 'win32'
            else next(
                str(b)
                async for b in aiopath.AsyncPath(__file__).parent.glob(
                    'tsschecker*.exe'
                )
                if await b.is_file()
            ),
            '-d',
            device.identifier,
            '-B',
            device.board,
            '-e',
            f"0x{device.ecid}",
            '-m',
            str(manifest),
            '--save-path',
            str(tmpdir),
            '-s',
        ]

        if device.apnonce is not None:
            args.append('--apnonce')
            args.append(device.apnonce)
            save_path.append(device.apnonce)
        else:
            generators.append('0x1111111111111111')
            generators.append('0xbd34a880be0b53f3')
            save_path.append('no-apnonce')

        if device.generator is not None and device.generator not in generators:
            generators.append(device.generator)

        save_path = aiopath.AsyncPath('/'.join(save_path))
        if len(generators) == 0:
            if len([blob async for blob in save_path.glob('*.shsh*')]) == 1:
                return True

            cmd = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE
            )
            stdout = (await cmd.communicate())[0]

            if 'Saved shsh blobs!' not in stdout.decode():
                return False

        else:
            if len([blob async for blob in save_path.glob('*.shsh*')]) == len(
                generators
            ):
                return True

            elif len([blob async for blob in save_path.glob('*.shsh*')]) > 0:
                async for blob in save_path.glob('*.shsh*'):
                    await blob.unlink()

            args.append('-g')
            for gen in generators:
                args.append(gen)
                cmd = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE
                )
                stdout = (await cmd.communicate())[0]

                if 'Saved shsh blobs!' not in stdout.decode():
                    return False

                args.pop(-1)

        await save_path.mkdir(parents=True, exist_ok=True)
        async for blob in tmpdir.glob('*.shsh*'):
            await blob.rename(save_path / blob.name)

        return True

    async def _upload_file(self, file: aiopath.AsyncPath) -> str:
        async with file.open('rb') as f, self.bot.session.put(
            f'https://up.psty.io/{file.name}', data=f
        ) as resp:
            data = await resp.text()

        return data.splitlines()[-1].split(':', 1)[1][1:]

    async def backup_blobs(
        self, tmpdir: aiopath.AsyncPath, *ecids: list[str]
    ) -> Optional[str]:
        blobdir = aiopath.AsyncPath('Data/Blobs')
        tmpdir = tmpdir / 'SHSH Blobs'
        await tmpdir.mkdir()

        if len(ecids) == 1:
            async for firm in blobdir.glob(f'{ecids[0]}/*'):
                await asyncio.to_thread(shutil.copytree, firm, tmpdir / firm.name)

        else:
            for ecid in ecids:
                try:
                    await asyncio.to_thread(
                        shutil.copytree, blobdir / ecid, tmpdir / ecid
                    )
                except FileNotFoundError:
                    pass

        if len([blob async for blob in tmpdir.glob('*/') if await blob.is_dir()]) == 0:
            return

        await asyncio.to_thread(
            shutil.make_archive, tmpdir.parent / 'Blobs', 'zip', tmpdir
        )
        return await self._upload_file(tmpdir.parent / 'Blobs.zip')

    async def save_device_blobs(self, device: dict) -> None:
        stats = {
            'saved_blobs': list(),
            'failed_blobs': list(),
        }

        firms = await self.get_firms(device.identifier)
        for firm in [f for f in firms if f['signed'] == True]:
            if any(
                firm['buildid'] == saved_firm['buildid']
                for saved_firm in device.saved_blobs
            ):  # If we've already saved blobs for this version, skip
                continue

            async with aiofiles.tempfile.TemporaryDirectory() as tmpdir:
                manifest = await self._get_manifest(
                    firm['url'], tmpdir
                ) or await asyncio.to_thread(
                    self._sync_get_manifest, firm['url'], tmpdir
                )
                saved_blob = (
                    await self._save_blob(device, firm, str(manifest), manifest.parent)
                    if manifest != False
                    else False
                )

            if saved_blob is True:
                device.saved_blobs.append(
                    {x: y for x, y in firm.items() if x not in ('url', 'signed')}
                )
                stats['saved_blobs'].append(firm)
            else:
                stats['failed_blobs'].append(firm)

        stats['device'] = device

        return stats

    async def save_user_blobs(self, user: int, devices: list[dict]) -> None:
        tasks = [self.save_device_blobs(device) for device in devices]
        data = await asyncio.gather(*tasks)

        await self.bot.db.execute(
            'UPDATE autotss SET devices = ? WHERE user = ?',
            (ujson.dumps([d['device'] for d in data]), user),
        )
        await self.bot.db.commit()

        user_stats = {
            'blobs_saved': sum([len(d['saved_blobs']) for d in data]),
            'devices_saved': len([d for d in data if d['saved_blobs']]),
            'devices': [d['device'] for d in data],
        }

        for d in range(len(user_stats['devices'])):
            user_stats['devices'][d]['failed_blobs'] = data[d]['failed_blobs']

        return user_stats

    async def sem_call(self, func, *args):
        async with self.sem:
            return await func(*args)


def setup(bot: discord.Bot):
    bot.add_cog(UtilsCog(bot))
