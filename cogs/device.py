from discord.errors import NotFound, Forbidden
from discord import Option
from views.buttons import SelectView, PaginatorView
from views.selects import DropdownView

import aiofiles
import aiopath
import aiosqlite
import asyncio
import discord
import json
import shutil


class DeviceCog(discord.Cog, name='Device'):
    def __init__(self, bot):
        self.bot = bot
        self.utils = self.bot.get_cog('Utilities')

    device = discord.SlashCommandGroup('devices', 'Device commands', guild_ids=(729946499102015509,))

    @device.command(name='add', description='Add a device to AutoTSS.')
    async def add_device(self, ctx: discord.ApplicationContext) -> None:
        if await self.utils.whitelist_check(ctx) != True:
            return

        timeout_embed = discord.Embed(title='Add Device', description='No response given in 5 minutes, cancelling.')
        cancelled_embed = discord.Embed(title='Add Device', description='Cancelled.')
        invalid_embed = discord.Embed(title='Error')

        for x in (timeout_embed, cancelled_embed):
            x.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

        max_devices = 10 #TODO: Export this option to a separate config file

        async with aiosqlite.connect(self.utils.db_path) as db, db.execute('SELECT devices from autotss WHERE user = ?', (ctx.author.id,)) as cursor:
            try:
                devices = json.loads((await cursor.fetchone())[0])
            except TypeError:
                devices = list()
                await db.execute('INSERT INTO autotss(user, devices, enabled) VALUES(?,?,?)', (ctx.author.id, json.dumps(devices), True))
                await db.commit()

        if (len(devices) >= max_devices) and (await ctx.bot.is_owner(ctx.author) == False): # Error out if you attempt to add over 'max_devices' devices, and if you're not the owner of the bot
            invalid_embed.description = f'You cannot add over {max_devices} devices to AutoTSS.'
            await ctx.respond(embed=invalid_embed, ephemeral=True)
            return

        device = dict()
        for x in range(4): # Loop that gets all of the required information to save blobs with from the user
            descriptions = (
                'Enter a name for your device.',
                "Enter your device's identifier. This can be found with [AIDA64](https://apps.apple.com/app/apple-store/id979579523) under the `Device` section (as `Device String`).",
                f"Enter your device's ECID (hex).\n*If you'd like to keep your ECID private, you can DM your ECID to {self.bot.user.mention}.*",
                "Enter your device's Board Config. This value ends in `ap`, and can be found with [AIDA64](https://apps.apple.com/app/apple-store/id979579523) under the `Device` section (as `Device Id`), [System Info](https://arx8x.github.io/depictions/systeminfo.html) under the `Platform` section, or by running `gssc | grep HWModelStr` in a terminal on your iOS device."
            )

            embed = discord.Embed(title='Add Device', description='\n'.join((descriptions[x], 'Type `cancel` to cancel.')))
            embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

            if (x == 3) and ('boardconfig' in device.keys()): # If we got boardconfig from API, no need to get it from user
                continue

            #TODO: Figure out how I'll have a cancel button through this loop
            if x == 0:
                await ctx.respond(embed=embed, ephemeral=True)
            else:
                await ctx.edit(embed=embed)

            # Wait for a response from the user, and error out if the user takes over 5 minutes to respond
            try:
                response = await self.bot.wait_for('message', check=lambda message: message.author == ctx.author and (message.channel == ctx.channel or message.channel.type == discord.ChannelType.private), timeout=300)
                if x == 0:
                    answer = response.content # Don't make the device's name lowercase
                else:
                    answer = response.content.lower()

            except asyncio.exceptions.TimeoutError:
                await ctx.edit(embed=timeout_embed)
                return

            # Delete the message
            try:
                await response.delete()
            except NotFound:
                pass
            except Forbidden as e:
                if x != 2:
                    raise e

            answer = discord.utils.remove_markdown(answer)
            if answer.lower().startswith('cancel'):
                await ctx.edit(embed=cancelled_embed)
                return

            # Make sure given information is valid
            if x == 0:
                device['name'] = answer
                name_check = await self.utils.check_name(device['name'], ctx.author.id)
                if name_check != True:
                    if name_check == 0:
                        invalid_embed.description = f"Device name `{device['name']}` is not valid. A device's name cannot be over 20 characters long."
                    elif name_check == -1:
                        invalid_embed.description = f"Device name `{device['name']}` is not valid. You cannot use a device's name more than once."

                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    await ctx.edit(embed=invalid_embed)
                    return

            elif x == 1:
                device['identifier'] = answer.replace(' ', '').replace('devicestring:', '')
                if 'appletv' in device['identifier']:
                    device['identifier'] = 'TV'.join(device['identifier'].capitalize().split('tv'))
                else:
                    device['identifier'] = 'P'.join(device['identifier'].split('p'))

                if await self.utils.check_identifier(device['identifier']) is False:
                    invalid_embed.description = f"Device Identifier `{answer}` is not valid."
                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    await ctx.edit(embed=invalid_embed)
                    return

                # If there's only one board for the device, grab the boardconfig now
                api = await self.utils.fetch_ipswme_api(device['identifier'])
                valid_boards = [board for board in api['boards'] if board['boardconfig'].lower().endswith('ap')]
                if len(valid_boards) == 1: # Exclude development boards that may pop up
                    device['boardconfig'] = valid_boards[0]['boardconfig'].lower()

            elif x == 2:
                device['ecid'] = answer[2:] if answer.startswith('0x') else answer
                ecid_check = await self.utils.check_ecid(device['ecid'])
                if ecid_check != True:
                    invalid_embed.description = f"Device ECID `{answer}` is not valid."
                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    if ecid_check == -1:
                        invalid_embed.description += ' This ECID has already been added to AutoTSS.'

                    await ctx.edit(embed=invalid_embed)
                    return

            elif x == 3:
                device['boardconfig'] = answer.replace(' ', '').replace('deviceid:', '')
                if await self.utils.check_boardconfig(device['identifier'], device['boardconfig']) is False:
                    invalid_embed.description = f"Device boardconfig `{answer}` is not valid."
                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    await ctx.edit(embed=invalid_embed)
                    return

        generator_description = [
            'Would you like to save SHSH blobs with a custom generator?',
            'This value begins with `0x` and is followed by 16 hexadecimal characters.'
        ]

        cpid = await self.utils.get_cpid(device['identifier'], device['boardconfig'])
        if 0x8020 <= cpid < 0x8900:
            generator_description.append('\n*If you choose to, you **will** need to provide a matching ApNonce for SHSH blobs to be saved correctly.*')
            generator_description.append('*Guide for jailbroken A12+ devices: [Click here](https://gist.github.com/m1stadev/5464ea557c2b999cb9324639c777cd09#getting-a-generator-apnonce-pair-jailbroken)*')
            generator_description.append('*Guide for non-jailbroken A12+ devices: [Click here](https://gist.github.com/m1stadev/5464ea557c2b999cb9324639c777cd09#getting-a-generator-apnonce-pair-non-jailbroken)*')

        embed = discord.Embed(title='Add Device', description='\n'.join(generator_description)) # Ask the user if they'd like to save blobs with a custom generator
        embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

        buttons = [{
            'label': 'Yes',
            'style': discord.ButtonStyle.primary
        }, {
            'label': 'No',
            'style': discord.ButtonStyle.secondary
        }, {
            'label': 'Cancel',
            'style': discord.ButtonStyle.danger
        }]

        view = SelectView(buttons, ctx)
        await ctx.edit(embed=embed, view=view)
        await view.wait()
        if view.answer is None:
            timeout_embed.description = 'No response given in 1 minute, cancelling.'
            await ctx.edit(embed=timeout_embed)
            return

        if view.answer == 'Yes':
            embed = discord.Embed(title='Add Device', description='Please enter the custom generator you wish to save SHSH blobs with.\nType `cancel` to cancel.')
            embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
            await ctx.edit(embed=embed)

            try:
                response = await self.bot.wait_for('message', check=lambda message: message.author == ctx.author, timeout=300)
                answer = discord.utils.remove_markdown(response.content).lower()
            except asyncio.exceptions.TimeoutError:
                await ctx.edit(embed=timeout_embed)
                return

            try:
                await response.delete()
            except discord.errors.NotFound:
                pass

            if answer.startswith('cancel'):
                await ctx.edit(embed=cancelled_embed)
                return

            else:
                device['generator'] = answer
                if await self.utils.check_generator(device['generator']) is False:
                    invalid_embed.description = f"Generator `{device['generator']}` is not valid."
                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    await ctx.edit(embed=invalid_embed)
                    return

        elif view.answer == 'No':
            device['generator'] = None

        elif view.answer == 'Cancel':
            await ctx.edit(embed=cancelled_embed)
            return

        apnonce_description = [
            'Would you like to save SHSH blobs with a custom ApNonce?',
            f'This value is hexadecimal and {40 if 0x8010 <= cpid < 0x8900 else 64} characters long.',
            'This is **NOT** the same as your **generator**, which begins with `0x` and is followed by 16 hexadecimal characters.'
        ]

        if 0x8020 <= cpid < 0x8900:
            apnonce_description.append('\n*You must save blobs with an ApNonce, or else your SHSH blobs **will not work**. More info [here](https://www.reddit.com/r/jailbreak/comments/f5wm6l/tutorial_repost_easiest_way_to_save_a12_blobs/).*')

        embed = discord.Embed(title='Add Device', description='\n'.join(apnonce_description)) # Ask the user if they'd like to save blobs with a custom ApNonce
        embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

        buttons = [{
            'label': 'Yes',
            'style': discord.ButtonStyle.primary
        }, {
            'label': 'No',
            'style': discord.ButtonStyle.secondary,
            'disabled': 0x8020 <= cpid < 0x8900 # Don't allow A12+ users to save blobs without an ApNonce
        }, {
            'label': 'Cancel',
            'style': discord.ButtonStyle.danger
        }]

        view = SelectView(buttons, ctx)
        await ctx.edit(embed=embed, view=view)
        await view.wait()
        if view.answer is None:
            timeout_embed.description = 'No response given in 1 minute, cancelling.'
            await ctx.edit(embed=timeout_embed)
            return

        if view.answer == 'Yes':
            embed = discord.Embed(title='Add Device', description='Please enter the custom ApNonce you wish to save SHSH blobs with.\nType `cancel` to cancel.')
            embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
            await ctx.edit(embed=embed)

            try:
                response = await self.bot.wait_for('message', check=lambda message: message.author == ctx.author, timeout=300)
                answer = discord.utils.remove_markdown(response.content.lower())
            except asyncio.exceptions.TimeoutError:
                await ctx.edit(embed=timeout_embed)
                return

            try:
                await response.delete()
            except discord.errors.NotFound:
                pass

            if answer.startswith('cancel'):
                await ctx.edit(embed=cancelled_embed)
                return

            else:
                device['apnonce'] = answer
                if await self.utils.check_apnonce(cpid, device['apnonce']) is False:
                    invalid_embed.description = f"Device ApNonce `{device['apnonce']}` is not valid."
                    invalid_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                    await ctx.edit(embed=invalid_embed)
                    return

        elif view.answer == 'No':
            device['apnonce'] = None

        elif view.answer == 'Cancel':
            await ctx.edit(embed=cancelled_embed)
            return

        device['saved_blobs'] = list()

        # Add device information into the database
        devices.append(device)

        async with aiosqlite.connect(self.utils.db_path) as db:
            async with db.execute('SELECT devices FROM autotss WHERE user = ?', (ctx.author.id,)) as cursor:
                if await cursor.fetchone() is None:
                    sql = 'INSERT INTO autotss(devices, enabled, user) VALUES(?,?,?)'
                else:
                    sql = 'UPDATE autotss SET devices = ?, enabled = ? WHERE user = ?'

            await db.execute(sql, (json.dumps(devices), True, ctx.author.id))
            await db.commit()

        embed = discord.Embed(title='Add Device', description=f"Device `{device['name']}` added successfully!")
        embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
        await ctx.edit(embed=embed)

        await self.utils.update_device_count()

    @device.command(name='remove', description='Remove a device from AutoTSS.')
    async def remove_device(self, ctx: discord.ApplicationContext) -> None:
        if await self.utils.whitelist_check(ctx) != True:
            return

        cancelled_embed = discord.Embed(title='Remove Device', description='Cancelled.')
        invalid_embed = discord.Embed(title='Error', description='Invalid input given.')
        timeout_embed = discord.Embed(title='Remove Device', description='No response given in 1 minute, cancelling.')

        for x in (cancelled_embed, invalid_embed, timeout_embed):
            x.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

        async with aiosqlite.connect(self.utils.db_path) as db, db.execute('SELECT devices from autotss WHERE user = ?', (ctx.author.id,)) as cursor:
            try:
                devices = json.loads((await cursor.fetchone())[0])
            except TypeError:
                devices = list()

        if len(devices) == 0:
            embed = discord.Embed(title='Error', description='You have no devices added to AutoTSS.')
            await ctx.respond(embed=embed, ephemeral=True)
            return

        confirm_embed = discord.Embed(title='Remove Device')
        confirm_embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

        buttons = [{
            'label': 'Confirm',
            'style': discord.ButtonStyle.danger
        }, {
            'label': 'Cancel',
            'style': discord.ButtonStyle.secondary
        }]

        view = SelectView(buttons, ctx)
        if len(devices) > 1:
            device_options = list()
            for device in devices:
                device_options.append(discord.SelectOption(
                    label=device['name'],
                    description=f"ECID: {device['ecid']} | SHSH blob{'s' if len(device['saved_blobs']) != 1 else ''} saved: {len(device['saved_blobs'])}",
                    emoji='📱'
                ))

            device_options.append(discord.SelectOption(
                label='Cancel',
                emoji='❌'
            ))

            embed = discord.Embed(title='Remove Device', description="Please select the device you'd like to remove.")
            embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)

            dropdown = DropdownView(device_options, ctx, 'Device to remove...')
            await ctx.respond(embed=embed, view=dropdown, ephemeral=True)
            await dropdown.wait()
            if dropdown.answer is None:
                await ctx.edit(embed=timeout_embed)
                return

            if dropdown.answer == 'Cancel':
                await ctx.edit(embed=cancelled_embed)
                return

            num = next(devices.index(x) for x in devices if x['name'] == dropdown.answer)
            confirm_embed.description = f"Are you **absolutely sure** you want to delete `{devices[num]['name']}`?"
            await ctx.edit(embed=confirm_embed, view=view)

        else:
            num = 0
            confirm_embed.description = f"Are you **absolutely sure** you want to delete `{devices[num]['name']}`?"
            await ctx.respond(embed=confirm_embed, view=view, ephemeral=True)

        await view.wait()
        if view.answer is None:
            await ctx.edit(embed=timeout_embed)
            return

        if view.answer == 'Confirm':
            embed = discord.Embed(title='Remove Device', description='Removing device...')
            embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
            await ctx.edit(embed=embed)

            async with aiofiles.tempfile.TemporaryDirectory() as tmpdir:
                url = await self.utils.backup_blobs(aiopath.AsyncPath(tmpdir), devices[num]['ecid'])

            if url is not None:
                await asyncio.to_thread(shutil.rmtree, aiopath.AsyncPath(f"Data/Blobs/{devices[num]['ecid']}"))

                buttons = [{
                    'label': 'Download',
                    'style': discord.ButtonStyle.link,
                    'url': url
                }]

                view = SelectView(buttons, ctx, timeout=None)
                embed = discord.Embed(title='Remove Device', description=f"Device `{devices[num]['name']}` removed.\nSHSH Blobs:")
                await ctx.edit(embed=embed, view=view)

            else:
                embed = discord.Embed(title='Remove Device', description=f"Device `{devices[num]['name']}` removed.")
                embed.set_footer(text=ctx.author.display_name, icon_url=ctx.author.display_avatar.with_static_format('png').url)
                await ctx.edit(embed=embed)

            devices.pop(num)
            async with aiosqlite.connect(self.utils.db_path) as db:
                if len(devices) == 0:
                    await db.execute('DELETE FROM autotss WHERE user = ?', (ctx.author.id,))
                else:
                    await db.execute('UPDATE autotss SET devices = ? WHERE user = ?', (json.dumps(devices), ctx.author.id))
                await db.commit()

            await ctx.edit(embed=embed)
            await self.utils.update_device_count()

        elif view.answer == 'Cancel':
            await ctx.edit(embed=cancelled_embed)

    @device.command(name='list', description='List your added devices.')
    async def list_devices(self, ctx: discord.ApplicationContext, user: Option(discord.User, description='User to list SHSH blobs for', required=False)) -> None:
        if await self.utils.whitelist_check(ctx) != True:
            return

        if user is None:
            user = ctx.author

        async with aiosqlite.connect(self.utils.db_path) as db, db.execute('SELECT devices from autotss WHERE user = ?', (user.id,)) as cursor:
            try:
                devices = json.loads((await cursor.fetchone())[0])
            except TypeError:
                devices = list()

        if len(devices) == 0:
            embed = discord.Embed(title='Error', description=f"{'You have' if user == ctx.author else f'{user.mention} has'} no devices added to AutoTSS.")
            await ctx.respond(embed=embed, ephemeral=True)
            return

        device_embeds = list()
        for device in devices:
            num_blobs = len(device['saved_blobs'])
            device_embed = {
                'title': f"*{device['name']}*{f'  ({devices.index(device) + 1}/{len(devices)})' if len(devices) > 1 else ''}",
                'description': f"**{num_blobs}** SHSH blob{'s' if num_blobs != 1 else ''} saved",
                'fields': [{
                    'name': 'Device Identifier',
                    'value': f"`{device['identifier']}`",
                    'inline': False
                },
                {
                    'name': 'ECID',
                    'value': f"`{device['ecid']}`",
                    'inline': False
                },
                {
                    'name': 'Board Config',
                    'value': f"`{device['boardconfig']}`",
                    'inline': False
                }],
                'footer': {
                    'text': ctx.author.display_name,
                    'icon_url': str(ctx.author.display_avatar.with_static_format('png').url)
                }
            }

            if device['generator'] is not None:
                device_embed['fields'].append({
                    'name': 'Custom Generator',
                    'value': f"`{device['generator']}`",
                    'inline': False
                })

            if device['apnonce'] is not None:
                device_embed['fields'].append({
                    'name': 'Custom ApNonce',
                    'value': f"`{device['apnonce']}`",
                    'inline': False
                })

            device_embeds.append(discord.Embed.from_dict(device_embed))

        if len(device_embeds) == 1:
            await ctx.respond(embed=device_embeds[0], ephemeral=True)
            return

        paginator = PaginatorView(device_embeds, ctx)
        await ctx.respond(embed=device_embeds[paginator.embed_num], view=paginator, ephemeral=True)

def setup(bot):
    bot.add_cog(DeviceCog(bot))
