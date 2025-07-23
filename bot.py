"""
RTanks Online Discord Bot
Core bot functionality with slash commands.
"""

import discord
from discord.ext import commands
import aiohttp
import asyncio
import time
import psutil
import os
from datetime import datetime, timedelta
import logging
import re

from scraper import RTanksScraper
from utils import format_number, format_exact_number, get_rank_emoji, format_duration, compare_equipment_quality
from config import RANK_EMOJIS, PREMIUM_EMOJI, GOLD_BOX_EMOJI, RTANKS_BASE_URL

logger = logging.getLogger(__name__)

class RTanksBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        # Bot statistics
        self.start_time = datetime.now()
        self.commands_processed = 0
        self.scraping_successes = 0
        self.scraping_failures = 0
        self.total_scraping_time = 0.0
        
        # Initialize scraper
        self.scraper = RTanksScraper()
    
    async def setup_hook(self):
        """Setup hook called when bot is starting up."""
        # Register commands with the command tree
        self.tree.command(name="player", description="Get RTanks player statistics")(self.player_command_handler)
        self.tree.command(name="botstats", description="Display bot performance statistics")(self.botstats_command_handler)
        self.tree.command(name="compare", description="Compare two RTanks players")(self.compare_command_handler)
        
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Set bot status
        activity = discord.Game(name="RTanks Online")
        await self.change_presence(activity=activity)

    @discord.app_commands.describe(username="RTanks player username to lookup")
    async def player_command_handler(self, interaction: discord.Interaction, username: str):
        """Slash command to get player statistics."""
        await interaction.response.defer()
        
        start_time = time.time()
        self.commands_processed += 1
        
        try:
            # Scrape player data
            player_data = await self.scraper.get_player_data(username.strip())
            
            if not player_data:
                embed = discord.Embed(
                    title="❌ Player Not Found",
                    description=f"Could not find player data for `{username}`. Please check the username and try again.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                self.scraping_failures += 1
                return
            
            # Create player embed
            embed = await self._create_player_embed(player_data)
            await interaction.followup.send(embed=embed)
            
            # Update statistics
            scraping_time = time.time() - start_time
            self.total_scraping_time += scraping_time
            self.scraping_successes += 1
            
        except Exception as e:
            logger.error(f"Error processing player command: {e}")
            
            embed = discord.Embed(
                title="⚠️ Error",
                description="An error occurred while fetching player data. The RTanks website might be temporarily unavailable.",
                color=0xffa500
            )
            await interaction.followup.send(embed=embed)
            self.scraping_failures += 1

    @discord.app_commands.describe(
        player1="First RTanks player username",
        player2="Second RTanks player username"
    )
    async def compare_command_handler(self, interaction: discord.Interaction, player1: str, player2: str):
        """Slash command to compare two RTanks players."""
        await interaction.response.defer()
        
        start_time = time.time()
        self.commands_processed += 1
        
        try:
            # Clean usernames
            player1 = player1.strip()
            player2 = player2.strip()
            
            if player1.lower() == player2.lower():
                embed = discord.Embed(
                    title="❌ Invalid Comparison",
                    description="Cannot compare a player with themselves. Please provide two different usernames.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Fetch data for both players
            logger.info(f"Fetching data for {player1} and {player2}")
            
            # Fetch both players concurrently
            player1_task = self.scraper.get_player_data(player1)
            player2_task = self.scraper.get_player_data(player2)
            
            player1_data, player2_data = await asyncio.gather(player1_task, player2_task, return_exceptions=True)
            
            # Check for errors in data fetching
            if isinstance(player1_data, Exception):
                logger.error(f"Error fetching {player1}: {player1_data}")
                player1_data = None
            if isinstance(player2_data, Exception):
                logger.error(f"Error fetching {player2}: {player2_data}")
                player2_data = None
            
            # Handle cases where one or both players are not found
            if not player1_data and not player2_data:
                embed = discord.Embed(
                    title="❌ Players Not Found",
                    description=f"Could not find data for either `{player1}` or `{player2}`. Please check the usernames and try again.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                self.scraping_failures += 2
                return
            elif not player1_data:
                embed = discord.Embed(
                    title="❌ Player Not Found",
                    description=f"Could not find data for `{player1}`. Please check the username and try again.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                self.scraping_failures += 1
                return
            elif not player2_data:
                embed = discord.Embed(
                    title="❌ Player Not Found",
                    description=f"Could not find data for `{player2}`. Please check the username and try again.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                self.scraping_failures += 1
                return
            
            # Create comparison embed
            embed = await self._create_comparison_embed(player1_data, player2_data)
            await interaction.followup.send(embed=embed)
            
            # Update statistics
            scraping_time = time.time() - start_time
            self.total_scraping_time += scraping_time
            self.scraping_successes += 2
            
        except Exception as e:
            logger.error(f"Error processing compare command: {e}")
            
            embed = discord.Embed(
                title="⚠️ Error",
                description="An error occurred while comparing players. The RTanks website might be temporarily unavailable.",
                color=0xffa500
            )
            await interaction.followup.send(embed=embed)
            self.scraping_failures += 1

    async def botstats_command_handler(self, interaction: discord.Interaction):
        """Slash command to display bot statistics."""
        await interaction.response.defer()
        
        self.commands_processed += 1
        
        # Calculate bot latency
        bot_latency = round(self.latency * 1000, 2)
        
        # Calculate average scraping latency
        avg_scraping_latency = 0
        if self.scraping_successes > 0:
            avg_scraping_latency = round((self.total_scraping_time / self.scraping_successes) * 1000, 2)
        
        # Calculate uptime
        uptime = datetime.now() - self.start_time
        uptime_str = format_duration(uptime.total_seconds())
        
        # Get system stats
        process = psutil.Process(os.getpid())
        memory_usage = round(process.memory_info().rss / 1024 / 1024, 2)  # MB
        cpu_usage = round(process.cpu_percent(interval=1), 1)
        
        # Calculate success rate
        total_scrapes = self.scraping_successes + self.scraping_failures
        success_rate = 0
        if total_scrapes > 0:
            success_rate = round((self.scraping_successes / total_scrapes) * 100, 1)
        
        embed = discord.Embed(
            title="🤖 Bot Statistics",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        # Performance metrics
        embed.add_field(
            name="📡 Latency",
            value=f"**Discord API:** {bot_latency}ms\n**Scraping Avg:** {avg_scraping_latency}ms",
            inline=True
        )
        
        embed.add_field(
            name="⏱️ Uptime",
            value=uptime_str,
            inline=True
        )
        
        embed.add_field(
            name="🌐 Servers",
            value=f"{len(self.guilds)}",
            inline=True
        )
        
        # Command statistics
        embed.add_field(
            name="📊 Commands",
            value=f"**Total Processed:** {format_number(self.commands_processed)}\n**Success Rate:** {success_rate}%",
            inline=True
        )
        
        # Scraping statistics
        embed.add_field(
            name="🔍 Scraping Stats",
            value=f"**Successful:** {format_number(self.scraping_successes)}\n**Failed:** {format_number(self.scraping_failures)}",
            inline=True
        )
        
        # System resources
        embed.add_field(
            name="💻 System Resources",
            value=f"**Memory:** {memory_usage} MB\n**CPU:** {cpu_usage}%",
            inline=True
        )
        
        # Website status
        website_status = await self._check_website_status()
        embed.add_field(
            name="🌍 Website Status",
            value=website_status,
            inline=False
        )
        
        embed.set_footer(text="RTanks Online Bot", icon_url=self.user.display_avatar.url if self.user else None)
        
        await interaction.followup.send(embed=embed)

    async def _create_player_embed(self, player_data):
        """Create a formatted embed for player data."""
        # Create embed with activity status
        activity_status = "Online" if player_data['is_online'] else "Offline"
        profile_url = f"{RTANKS_BASE_URL}/user/{player_data['username']}"
        embed = discord.Embed(
            title=f"{player_data['username']}",
            url=profile_url,
            description=f"**Activity:** {activity_status}",
            color=0x00ff00 if player_data['is_online'] else 0x808080,
            timestamp=datetime.now()
        )
        
        # Player rank and basic info - make rank emoji bigger
        rank_emoji = get_rank_emoji(player_data['rank'])
        
        # Extract the emoji ID from the custom Discord emoji and use it as thumbnail
        import re
        emoji_match = re.search(r':(\d+)>', rank_emoji)
        if emoji_match:
            emoji_id = emoji_match.group(1)
            emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
            embed.set_thumbnail(url=emoji_url)
        
        # Rank field with just the rank name, no emoji
        embed.add_field(
            name="Rank",
            value=f"**{player_data['rank']}**",
            inline=True
        )
        
        # Experience - show current/max format like "105613/125000"
        if 'max_experience' in player_data and player_data['max_experience']:
            exp_display = f"{format_exact_number(player_data['experience'])}/{format_exact_number(player_data['max_experience'])}"
        else:
            exp_display = f"{format_exact_number(player_data['experience'])}"
        
        embed.add_field(
            name="Experience",
            value=exp_display,
            inline=True
        )
        
        # Premium status - always show premium emoji
        premium_status = "Yes" if player_data['premium'] else "No"
        embed.add_field(
            name="Premium",
            value=f"{PREMIUM_EMOJI} {premium_status}",
            inline=True
        )
        
        # Combat Stats - remove non-custom emojis
        combat_stats = (
            f"**Kills:** {format_exact_number(player_data['kills'])}\n"
            f"**Deaths:** {format_exact_number(player_data['deaths'])}\n"
            f"**K/D:** {player_data['kd_ratio']}"
        )
        embed.add_field(
            name="Combat Stats",
            value=combat_stats,
            inline=True
        )
        
        # Other Stats - always show gold box emoji
        other_stats = (
            f"{GOLD_BOX_EMOJI} **Gold Boxes:** {player_data['gold_boxes']}\n"
            f"**Group:** {player_data['group']}"
        )
        embed.add_field(
            name="Other Stats",
            value=other_stats,
            inline=True
        )
        
        # Equipment - show all equipment with exact modification levels
        if player_data['equipment']:
            equipment_text = ""
            
            if player_data['equipment'].get('turrets'):
                turrets = ", ".join(player_data['equipment']['turrets'])  # Show all turrets
                equipment_text += f"**Turrets:** {turrets}\n"
            
            if player_data['equipment'].get('hulls'):
                hulls = ", ".join(player_data['equipment']['hulls'])  # Show all hulls
                equipment_text += f"**Hulls:** {hulls}"
            
            if equipment_text:
                embed.add_field(
                    name="Equipment",
                    value=equipment_text,
                    inline=False
                )
        
        embed.set_footer(text="Data from ratings.ranked-rtanks.online")
        
        return embed

    async def _create_comparison_embed(self, player1_data, player2_data):
        """Create a formatted embed for player comparison."""
        p1_name = player1_data['username']
        p2_name = player2_data['username']
        
        embed = discord.Embed(
            title="Player Comparison",
            description=f"**{p1_name}** vs **{p2_name}**",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        # Experience comparison
        p1_exp = player1_data.get('experience', 0)
        p2_exp = player2_data.get('experience', 0)
        
        if p1_exp > p2_exp:
            exp_winner = f"**{p1_name}** ({format_exact_number(p1_exp)})"
            exp_loser = f"{p2_name} ({format_exact_number(p2_exp)})"
        elif p2_exp > p1_exp:
            exp_winner = f"**{p2_name}** ({format_exact_number(p2_exp)})"
            exp_loser = f"{p1_name} ({format_exact_number(p1_exp)})"
        else:
            exp_winner = f"**Tie** ({format_exact_number(p1_exp)})"
            exp_loser = ""
        
        embed.add_field(
            name="Experience",
            value=f"{exp_winner}\n{exp_loser}".strip(),
            inline=True
        )
        
        # K/D ratio comparison
        p1_kd = float(player1_data.get('kd_ratio', '0.00'))
        p2_kd = float(player2_data.get('kd_ratio', '0.00'))
        
        if p1_kd > p2_kd:
            kd_winner = f"**{p1_name}** ({player1_data['kd_ratio']})"
            kd_loser = f"{p2_name} ({player2_data['kd_ratio']})"
        elif p2_kd > p1_kd:
            kd_winner = f"**{p2_name}** ({player2_data['kd_ratio']})"
            kd_loser = f"{p1_name} ({player1_data['kd_ratio']})"
        else:
            kd_winner = f"**Tie** ({player1_data['kd_ratio']})"
            kd_loser = ""
        
        embed.add_field(
            name="K/D Ratio",
            value=f"{kd_winner}\n{kd_loser}".strip(),
            inline=True
        )
        
        # Gold boxes comparison
        p1_gold = player1_data.get('gold_boxes', 0)
        p2_gold = player2_data.get('gold_boxes', 0)
        
        if p1_gold > p2_gold:
            gold_winner = f"**{p1_name}** ({format_exact_number(p1_gold)})"
            gold_loser = f"{p2_name} ({format_exact_number(p2_gold)})"
        elif p2_gold > p1_gold:
            gold_winner = f"**{p2_name}** ({format_exact_number(p2_gold)})"
            gold_loser = f"{p1_name} ({format_exact_number(p1_gold)})"
        else:
            gold_winner = f"**Tie** ({format_exact_number(p1_gold)})"
            gold_loser = ""
        
        embed.add_field(
            name=f"{GOLD_BOX_EMOJI} Gold Boxes",
            value=f"{gold_winner}\n{gold_loser}".strip(),
            inline=True
        )
        

        
        # Add player details section
        p1_details = (
            f"**{p1_name}**\n"
            f"Rank: {player1_data['rank']}\n"
            f"Kills: {format_exact_number(player1_data.get('kills', 0))}\n"
            f"Deaths: {format_exact_number(player1_data.get('deaths', 0))}"
        )
        
        p2_details = (
            f"**{p2_name}**\n"
            f"Rank: {player2_data['rank']}\n"
            f"Kills: {format_exact_number(player2_data.get('kills', 0))}\n"
            f"Deaths: {format_exact_number(player2_data.get('deaths', 0))}"
        )
        
        embed.add_field(
            name="Player 1",
            value=p1_details,
            inline=True
        )
        
        embed.add_field(
            name="Player 2",
            value=p2_details,
            inline=True
        )
        
        # Add empty field for spacing
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.set_footer(text="Data from ratings.ranked-rtanks.online")
        
        return embed

    async def _check_website_status(self):
        """Check if the RTanks website is accessible."""
        try:
            start_time = time.time()
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get('https://ratings.ranked-rtanks.online/') as response:
                    response_time = round((time.time() - start_time) * 1000, 2)
                    if response.status == 200:
                        return f"🟢 Online ({response_time}ms)"
                    else:
                        return f"🟡 Partial ({response.status})"
        except Exception:
            return "🔴 Offline"

    async def on_command_error(self, ctx, error):
        """Global error handler."""
        logger.error(f"Command error: {error}")
        
    async def close(self):
        """Clean up when bot is closing."""
        await self.scraper.close()
        await super().close()
