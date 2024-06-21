import discord
import logging
from dotenv import load_dotenv
import os

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord')

class ProjectsClient(discord.Client):
    def __init__(self, guild_id: int, *args, **kwargs):
        intents = discord.Intents.default()
        super().__init__(intents=intents, *args, **kwargs)
        self._guild_id = guild_id

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info('------')
        guild = self.get_guild(self._guild_id)
        if guild:
            await self.delete_non_entrance_channels(guild)
        await self.close()

    async def delete_non_entrance_channels(self, guild: discord.Guild):
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                if channel.name.lower() != "entrance" and channel.category is None:
                    logger.info(f'Deleting channel: {channel.name} (ID: {channel.id})')
                    await channel.delete()
        logger.info('Finished deleting non-entrance channels.')

if __name__ == '__main__':
    load_dotenv()
    guild_id = int(os.getenv('DISCORD_GUILD_ID', ''))
    token = os.getenv('DISCORD_TOKEN', '')

    client = ProjectsClient(guild_id)
    client.run(token)