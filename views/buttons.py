import discord


class SelectButton(discord.ui.Button['SelectView']):
    def __init__(self, button: dict):
        super().__init__(**button)

        self.button_type = button['label'].lower()

    async def callback(self, interaction: discord.Interaction):
        self.view.answer = self.button_type
        await self.view.on_timeout()
        self.view.stop()


class SelectView(discord.ui.View):
    def __init__(self, buttons: list[dict], *, public: bool=False, timeout: int=60):
        super().__init__(timeout=timeout)

        self.public = public
        self.answer = None

        for button in buttons:
            self.add_item(SelectButton(button))

    async def interaction_check(self, interaction: discord.Interaction):
        if self.public == True or interaction.channel.type == discord.ChannelType.private:
            return True

        return interaction.user == self.message.reference.cached_message.author

    async def on_timeout(self):
        self.clear_items()
        await self.message.edit(view=self)


class PaginatorView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], *, public: bool=False, timeout: int=60):
        super().__init__(timeout=timeout)

        self.public = public
        self.embeds = embeds
        self.embed_num = 0

    async def update_interaction(self, interaction: discord.Interaction):
        self.children[0].disabled = False if self.embed_num > 1 else True
        self.children[1].disabled = False if self.embed_num > 0 else True
        self.children[2].disabled = False if self.embed_num < (len(self.embeds) - 1) else True
        self.children[3].disabled = False if self.embed_num < (len(self.embeds) - 2) else True

        await interaction.response.edit_message(embed=self.embeds[self.embed_num], view=self)

    @discord.ui.button(emoji='⏪', style=discord.ButtonStyle.secondary, disabled=True)
    async def page_beginning(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.embed_num = 0
        await self.update_interaction(interaction)

    @discord.ui.button(emoji='⬅️', style=discord.ButtonStyle.secondary, disabled=True)
    async def page_backward(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.embed_num -= 1
        await self.update_interaction(interaction)

    @discord.ui.button(emoji='➡️', style=discord.ButtonStyle.secondary)
    async def page_forward(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.embed_num += 1
        await self.update_interaction(interaction)

    @discord.ui.button(emoji='⏩', style=discord.ButtonStyle.secondary)
    async def page_end(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.embed_num = len(self.embeds) - 1
        await self.update_interaction(interaction)

    async def interaction_check(self, interaction: discord.Interaction):
        if self.public == True or interaction.channel.type == discord.ChannelType.private:
            return True

        return interaction.user == self.message.reference.cached_message.author

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

        await self.message.edit(view=self)