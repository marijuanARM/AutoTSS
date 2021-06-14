from aioify import aioify
from discord.ext import commands, tasks
import aiofiles
import aiohttp
import aiosqlite
import discord
import glob
import json
import os
import remotezip
import shutil


class Utils(commands.Cog):
	def __init__(self, bot):
		self.bot = bot
		self.os = aioify(os, name='os')
		self.shutil = aioify(shutil, name='shutil')
		self.get_invite.start()

	@tasks.loop(count=1)
	async def get_invite(self): self.invite = f'https://discord.com/oauth2/authorize?client_id={self.bot.user.id}&scope=bot&permissions=93184'

	@get_invite.before_loop
	async def before_get_invite(self):
		await self.bot.wait_until_ready()

	async def backup_blobs(self, tmpdir, *ecids):
		await self.os.mkdir(f'{tmpdir}/Blobs')

		for ecid in ecids:
			try:
				await self.shutil.copytree(f'Data/Blobs/{ecid}', f'{tmpdir}/Blobs/{ecid}')
			except FileNotFoundError:
				pass

		if len(glob.glob(f'{tmpdir}/Blobs/*')) == 0:
			return

		await self.shutil.make_archive(f'{tmpdir}_blobs', 'zip', tmpdir)
		return await self.upload_file(f'{tmpdir}_blobs.zip', 'blobs.zip')

	async def buildid_to_version(self, identifier, buildid):
		api_url = f'https://api.ipsw.me/v4/device/{identifier}?type=ipsw'
		async with aiohttp.ClientSession() as session, session.get(api_url) as resp:
			api = await resp.json()

		return next(x['version'] for x in api['firmwares'] if x['buildid'] == buildid)

	async def check_apnonce(self, nonce):
		try:
			int(nonce, 16)
		except ValueError or TypeError:
			return False

		if len(nonce) not in (40, 64): # All ApNonce lengths are either 40 characters long, or 64 characters long
			return False

		return True

	async def check_boardconfig(self, session, identifier, boardconfig):
		if boardconfig[-2:] != 'ap':
			return False

		async with session.get(f'https://api.ipsw.me/v4/device/{identifier}?type=ipsw') as resp:
			api = await resp.json()

		if not any(x['boardconfig'].lower() == boardconfig for x in api['boards']): # If no boardconfigs for the given device identifier match the boardconfig, then return False
			return False
		else:
			return True

	async def check_ecid(self, ecid, user):
		if not 9 <= len(ecid) <= 16: # All ECIDs are between 9-16 characters
			return 0

		try:
			int(ecid, 16) # Make sure the ECID provided is hexadecimal, not decimal
		except ValueError or TypeError:
			return 0

		async with aiosqlite.connect('Data/autotss.db') as db: # Make sure the ECID the user provided isn't already a device added to AutoTSS.
			async with db.execute('SELECT devices from autotss WHERE user = ?', (user,)) as cursor:
				devices = (await cursor.fetchone())[0]

		if ecid in devices: # There's no need to convert the json string to a dict here
			return -1

		return True

	async def check_identifier(self, session, identifier):
		async with session.get('https://api.ipsw.me/v2.1/firmwares.json') as resp:
			if identifier not in (await resp.json())['devices']:
				return False
			else:
				return True

	async def check_name(self, name, user): # This function will return different values based on where it errors out at
		if not 4 <= len(name) <= 20: # Length check
			return 0

		async with aiosqlite.connect('Data/autotss.db') as db: # Make sure the user doesn't have any other devices with the same name added
			async with db.execute('SELECT devices from autotss WHERE user = ?', (user,)) as cursor:
				devices = json.loads((await cursor.fetchone())[0])

		if any(x['name'] == name.lower() for x in devices):
			return -1

		return True

	def get_manifest(self, url, dir):
		with remotezip.RemoteZip(url) as ipsw:
			manifest = ipsw.read(next(f for f in ipsw.namelist() if 'BuildManifest' in f))

		with open(f'{dir}/BuildManifest.plist', 'wb') as f:
			f.write(manifest)

		return f'{dir}/BuildManifest.plist'

	async def get_cpid(self, session, identifier):
		async with session.get(f'https://api.ipsw.me/v4/device/{identifier}?type=ipsw') as resp:
			api = await resp.json()

		return api['cpid']

	async def get_prefix(self, guild):
		async with aiosqlite.connect('Data/autotss.db') as db, db.execute('SELECT prefix FROM prefix WHERE guild = ?', (guild,)) as cursor:
			try:
				guild_prefix = (await cursor.fetchone())[0]
			except TypeError:
				await db.execute('INSERT INTO prefix(guild, prefix) VALUES(?,?)', (guild, 'b!'))
				await db.commit()
				guild_prefix = 'b!'

		return guild_prefix

	async def get_signed_buildids(self, session, identifier):
		api_url = f'https://api.ipsw.me/v4/device/{identifier}?type=ipsw'
		async with session.get(api_url) as resp:
			api = await resp.json()

		buildids = list()

		for firm in [x for x in api['firmwares'] if x['signed'] == True]:
			buildids.append({
					'version': firm['version'],
					'buildid': firm['buildid'],
					'url': firm['url'],
					'type': 'Release'

				})

		beta_api_url = f'https://api.m1sta.xyz/betas/{identifier}'
		async with session.get(beta_api_url) as resp:
			if resp.status != 200:
				beta_api = None
			else:
				beta_api = await resp.json()

		if beta_api is None:
			return buildids

		for firm in [x for x in beta_api if x['signed'] == True]:
			buildids.append({
					'version': firm['version'],
					'buildid': firm['buildid'],
					'url': firm['url'],
					'type': 'Beta'

				})

		return buildids

	async def update_device_count(self):
		async with aiosqlite.connect('Data/autotss.db') as db, db.execute('SELECT devices from autotss WHERE enabled = ?', (True,)) as cursor:
			all_devices = (await cursor.fetchall())

		num_devices = int()
		for user_devices in all_devices:
			devices = json.loads(user_devices[0])
			num_devices += len(devices)

		await self.bot.change_presence(activity=discord.Game(name=f"Ping me for help! | Saving blobs for {num_devices} device{'s' if num_devices != 1 else ''}"))

	async def upload_file(self, file, name):
		async with aiohttp.ClientSession() as session, aiofiles.open(file, 'rb') as f, session.put(f'https://up.psty.io/{name}', data=f) as response:
			resp = await response.text()

		return resp.splitlines()[-1].split(':', 1)[1][1:]

def setup(bot):
	bot.add_cog(Utils(bot))
