#!/usr/bin/env python3

from discord.ext import commands

import aiohttp
import aiosqlite
import asyncio
import discord
import glob
import os
import shutil
import sys


async def get_prefix(bot, message):
    if message.channel.type is discord.ChannelType.private:
        return 'b!'

    async with aiosqlite.connect('Data/autotss.db') as db, db.execute('SELECT prefix FROM prefix WHERE guild = ?', (message.guild.id,)) as cursor:
        try:
            guild_prefix = (await cursor.fetchone())[0]
        except TypeError:
            await db.execute('INSERT INTO prefix(guild, prefix) VALUES(?,?)', (message.guild.id, 'b!'))
            await db.commit()
            guild_prefix = 'b!'

    return commands.when_mentioned_or(guild_prefix)(bot, message)

async def startup():
    if sys.version_info.major < 3 and sys.version_info.minor < 9:
        sys.exit('[ERROR] AutoTSS requires Python 3.9 or higher. Exiting.')

    if sys.platform == 'win32':
        sys.exit('[ERROR] AutoTSS is not supported on Windows. Exiting.')

    if await asyncio.to_thread(shutil.which, 'tsschecker') is None:
        sys.exit('[ERROR] tsschecker is not installed on your system. Exiting.')

    if 'AUTOTSS_TOKEN' not in os.environ.keys():
        sys.exit("[ERROR] Bot token not set in 'AUTOTSS_TOKEN' environment variable. Exiting.")

    mentions = discord.AllowedMentions(everyone=False, roles=False)    
    (intents := discord.Intents.default()).members = True

    bot = commands.AutoShardedBot(
        help_command=None,
        command_prefix=get_prefix,
        intents=intents,
        allowed_mentions=mentions
    )

    bot.load_extension('cogs.utils') # Load utils cog first
    for cog in await asyncio.to_thread(glob.glob, 'cogs/*.py'):
        if 'utils.py' in cog:
            continue

        bot.load_extension(cog.replace('/', '.')[:-3])

    await asyncio.to_thread(os.makedirs, 'Data', exist_ok=True)
    async with aiosqlite.connect('Data/autotss.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS autotss(
            user INTEGER,
            devices JSON,
            enabled BOOLEAN
            )
            ''')
        await db.commit()

        await db.execute('''
            CREATE TABLE IF NOT EXISTS prefix(
            guild INTEGER,
            prefix TEXT
            )
            ''')
        await db.commit()

        await db.execute('''
            CREATE TABLE IF NOT EXISTS whitelist(
            guild INTEGER,
            channel INTEGER,
            enabled BOOLEAN
            )
            ''')
        await db.commit()

        await db.execute('''
            CREATE TABLE IF NOT EXISTS auto_frequency(
            time INTEGER
            )
            ''')
        await db.commit()

    async with aiohttp.ClientSession() as session:
        bot.session = session

        try:
            await bot.start(os.environ['AUTOTSS_TOKEN'])
        except discord.LoginFailure:
            sys.exit("[ERROR] Token invalid, make sure the 'AUTOTSS_TOKEN' environment variable is set to your bot token. Exiting.")
        except discord.PrivilegedIntentsRequired:
            sys.exit("[ERROR] Server Members Intent not enabled, go to 'https://discord.com/developers/applications' and enable the Server Members Intent. Exiting.")


if __name__ == '__main__':
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        pass

