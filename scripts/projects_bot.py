# Import necessary modules
import asyncio
import glob
import logging
import os
from datetime import datetime
from typing import Dict

import discord
import discord.ext.tasks
import pytz
import yaml
import json

# Import the fetch_gh_issues function from a local module
from fetch_gh_issues import fetch_gh_issues

# Set up logging
dlogger = logging.getLogger('discord')
logger = logging.getLogger('OHBM Bot')

# Define emojis for project roles
EMOJI_PROJECT_ROLES = list(
    "🐁🐂🐄🐇🐈🐉🐊🐋🐌"
    "🐍🐎🐏🐐🐑🐒🐓🐕🦛"
    "🦚🐘🐙🐚🐛🦢🐝🐞🦕"
    "🦖🐡🐢🐦🐧🦜🐩🐪🐬"
    "🐿🕊🦜🦂🦃🦆🦇🦈🦒"
    "🦉🦋🦎🦔🦦🦩🍀🌸🌻"
)

# Define hubs
HUBS = { 'americas': 'Americas', 'emea': 'EMEA', 'apac': 'APAC' }

# Message templates
ROLES_PROJECT_MESSAGE = "{emoji} [{title}]({link}): [@{key}](https://discordapp.com/channels/{guild}/{channel})"
ROLES_MESSAGE = """
> Please react to this message with the appropriate emoji for the project.
> 
> The emoji reaction will allow you to receive notifications from the project via the tag `@proj-<project name>`.
"""
ROLES_MESSAGE_ACK = """
The emojis were assigned to the projects *at random*, if you'd like to change your project's emoji, please contact the <@&{staff_role}>.
"""

# Define a class to represent a Project
class Project:
    def __init__(self, client, data, emoji):
        self.client = client
        self.guild = client.guild

        self.key = data['chatchannel'].lower()
        self.title = data['title']
        self.link = data['issue_link']
        self.emoji = emoji

        self.voice = client.voice_channels.get(self.key)
        self.text = client.text_channels.get(self.key)
        self.role = client.projects_roles.get(f'proj-{self.key}')
        self.react = None

    def __str__(self):
        s = (f"@{self.key}\n"
             f"title: {self.title}\n"
             f"link: {self.link}")
        if self.role is not None:
            s += f"\nrole: {self.role.id}"
        if self.voice is not None:
            s += f"\nchannels: {self.voice.id}"
        if self.text is not None:
            s += f"\nchannels: {self.text.id}"
        if self.react is not None:
            s += f"\nreact: {self.react[1]} on {self.react[0]}"
        return s

    def __await__(self):
        # Ensure role, channel, and channel permissions are set up
        yield from asyncio.create_task(self.ensure_role())
        yield from asyncio.create_task(self.ensure_channel())
        yield from asyncio.create_task(self.ensure_channel_permissions())
        return self

    async def ensure_role(self):
        if self.role is not None:
            return False

        self.role =  await self.guild.create_role(
            name=f'proj-{self.key}',
            mentionable=True,
        )
        await self.role.edit(position=2)
        return True

    async def ensure_channel(self):
        if self.voice is not None and self.text is not None:
            return False

        await self.ensure_role()

        if self.voice is None:
            self.voice = await self.guild.create_voice_channel(
                name=self.key,
                category=self.client.voice_category
            )
        if self.text is None:
            self.text = await self.guild.create_text_channel(
                name=self.key,
                category=self.client.text_category
            )
        return True

    async def ensure_channel_permissions(self):
        await self.ensure_channel()

        permission_hidden = discord.PermissionOverwrite(
            view_channel=False
        )
        permission_shown = discord.PermissionOverwrite(
            view_channel=True
        )
        overwrites = {
            self.guild.default_role: (
                permission_hidden
                if not self.client.sleep_mode
                else permission_shown
            ),
            self.client.roles['muted']: permission_hidden,
            self.client.roles['carl']: permission_shown,
            self.client.roles['hackathon-bot']: permission_shown,
            self.client.roles['staff']: permission_shown,
            self.role: permission_shown,
        }
        await self.voice.edit(overwrites=overwrites)
        await self.text.edit(overwrites=overwrites)
        return True

# Define the main client class for managing projects
class ProjectsClient(discord.Client):

    def __init__(self,
                 guild: int, roles_channel: int,
                 just_ensure_channels: bool = False,
                 just_ensure_events: bool = False,
                 sleep_mode: bool = False,
                 *args, **kwargs):

        # Initialize the client with default intents
        intents = discord.Intents.default()
        super().__init__(intents=intents, *args, **kwargs)

        self._just_ensure_channels = just_ensure_channels
        self._just_ensure_events = just_ensure_events
        self._guild_id = guild
        self._roles_channel_id = roles_channel
        self._sleep_mode = sleep_mode
        self._ready_to_bot = False

    # Cache the structures (roles, channels, etc.)
    async def cache_structures(self):
        guild = self.get_guild(self._guild_id)
        assert guild is not None
        self._guild: discord.Guild = guild

        roles_channel = self.get_channel(self._roles_channel_id)
        assert roles_channel is not None
        assert isinstance(roles_channel, discord.TextChannel)
        self._roles_channel: discord.TextChannel = roles_channel

        # Fetch specific roles by their IDs
        self._roles = {
            'staff': self._guild.get_role(920383461829795926),
            'carl': self._guild.get_role(971318302100033570),
            'hackathon-bot': self._guild.get_role(965650036308447276),
            'muted': self._guild.get_role(962429030714458162),
        }

        # Fetch specific channels by their IDs
        self._channels = {
            'lounge': self._guild.get_channel(1227957639317553254),
            'stage': self._guild.get_channel(1225939163078070383),
            'amphitheatre': self._guild.get_channel(1227957262988083283),
        }

        # Ensure project categories exist or create them
        voice_category, text_category = None, None
        for category in self._guild.categories:
            if category.name == 'Projects':
                voice_category = category
            elif category.name == 'Projects-text':
                text_category = category

        if voice_category is None:
            voice_category = await guild.create_category('Projects')
        if text_category is None:
            text_category = await guild.create_category('Projects-text')

        self._voice_category = voice_category
        self._text_category = text_category
        self._voice_channels = {
            ch.name: ch for ch in self._voice_category.voice_channels
        }
        self._text_channels = {
            ch.name: ch for ch in self._text_category.text_channels
        }
        self._projects_roles = {
            role.name: role
            for role in self.guild.roles
            if role.name.replace('proj-', '') in self._voice_channels
        }

    # Define properties to access cached structures
    @property
    def guild(self) -> discord.Guild:
        assert self._guild is not None
        return self._guild

    @property
    def roles_channel(self) -> discord.TextChannel:
        return self._roles_channel

    @property
    def voice_category(self) -> discord.CategoryChannel:
        return self._voice_category

    @property
    def text_category(self) -> discord.CategoryChannel:
        return self._text_category

    @property
    def voice_channels(self) -> Dict[str, discord.VoiceChannel]:
        return self._voice_channels

    @property
    def text_channels(self) -> Dict[str, discord.TextChannel]:
        return self._text_channels

    @property
    def projects_roles(self) -> Dict[str, discord.Role]:
        return self._projects_roles

    @property
    def roles(self) -> Dict[str, discord.Role]:
        return self._roles

    @property
    def sleep_mode(self) -> bool:
        return self._sleep_mode

    # Task to check for new issues and update projects every minute
    @discord.ext.tasks.loop(minutes=1)
    async def on_check_again(self):
        if not self._ready_to_bot:
            # Skip first iteration, we just did all this
            self._ready_to_bot = True
            return

        logger.info('Refreshing issues and all')
        current_project_ids = set(self.projects.keys())
        await self.cache_structures()
        await self.ensure_projects()

        # If here are new projects, refresh internal memory
        if current_project_ids.difference(self.projects.keys()):
            logger.info(f'Loaded {len(self.projects)} projects')
            logger.info('Checking roles messages')
            await self.ensure_roles_messages()
