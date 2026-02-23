import discord
#import re
import logging
from discord import app_commands, SelectOption
from discord.ui import View, Modal, TextInput, Select
import aiosqlite
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = "/app/data/bot.db"

intents = discord.Intents.default()
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ────────────────────────────────────────────────
#                  LOGGING SETUP
# ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("roles-bot")


async def log_to_channel(guild: discord.Guild, message: str, color: int = 0x5865f2):
    """Send a log embed to the configured log channel for this guild."""
    channel_id = await get_log_channel_id(guild.id)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    try:
        embed = discord.Embed(
            description=message,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Failed to send log to channel: {e}")


# Log colors
LOG_GREEN  = 0x2ecc71   # nickname updated, role added, channel synced
LOG_RED    = 0xe74c3c   # something removed or failed
LOG_BLUE   = 0x3498db   # informational / bulk actions
LOG_YELLOW = 0xf1c40f   # skipped / excluded


# ────────────────────────────────────────────────
#                  DATABASE
# ────────────────────────────────────────────────

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id        INTEGER PRIMARY KEY,
                staff_role_id   INTEGER,
                tag_prefix      TEXT DEFAULT '[',
                tag_suffix      TEXT DEFAULT '] ',
                log_channel_id  INTEGER,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tag_roles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                role_id     INTEGER NOT NULL,
                UNIQUE(guild_id, role_id),
                FOREIGN KEY(guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS excluded_channels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                channel_id  INTEGER NOT NULL,
                UNIQUE(guild_id, channel_id),
                FOREIGN KEY(guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS excluded_categories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                UNIQUE(guild_id, category_id),
                FOREIGN KEY(guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
            )
        """)
        # Add log_channel_id column if upgrading from older DB
        try:
            await db.execute("ALTER TABLE guilds ADD COLUMN log_channel_id INTEGER")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def get_guild_config(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT staff_role_id, tag_prefix, tag_suffix, log_channel_id FROM guilds WHERE guild_id = ?",
            (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "staff_role_id": row[0],
                    "prefix": row[1],
                    "suffix": row[2],
                    "log_channel_id": row[3]
                }
    return None


async def set_staff_role(guild_id: int, role_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO guilds (guild_id, staff_role_id) VALUES (?, ?)",
            (guild_id, role_id)
        )
        await db.commit()


async def set_log_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO guilds (guild_id, log_channel_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET log_channel_id = excluded.log_channel_id",
            (guild_id, channel_id)
        )
        await db.commit()


async def get_log_channel_id(guild_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT log_channel_id FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def add_tag_role(guild_id: int, role_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO tag_roles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id)
        )
        await db.commit()


async def remove_tag_role(guild_id: int, role_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM tag_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id)
        )
        await db.commit()


async def get_tag_role_ids(guild_id: int) -> set[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT role_id FROM tag_roles WHERE guild_id = ?", (guild_id,))
        return {row[0] async for row in cur}


async def add_excluded_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO excluded_channels (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id)
        )
        await db.commit()


async def remove_excluded_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM excluded_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id)
        )
        await db.commit()


async def get_excluded_channel_ids(guild_id: int) -> set[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT channel_id FROM excluded_channels WHERE guild_id = ?", (guild_id,))
        return {row[0] async for row in cur}


async def add_excluded_category(guild_id: int, category_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO excluded_categories (guild_id, category_id) VALUES (?, ?)",
            (guild_id, category_id)
        )
        await db.commit()


async def remove_excluded_category(guild_id: int, category_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM excluded_categories WHERE guild_id = ? AND category_id = ?",
            (guild_id, category_id)
        )
        await db.commit()


async def get_excluded_category_ids(guild_id: int) -> set[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT category_id FROM excluded_categories WHERE guild_id = ?", (guild_id,))
        return {row[0] async for row in cur}


# ────────────────────────────────────────────────
#                  NICKNAME LOGIC
# ────────────────────────────────────────────────

async def get_active_tag_role(member: discord.Member) -> discord.Role | None:
    config = await get_guild_config(member.guild.id)
    if not config:
        return None
    allowed_ids = await get_tag_role_ids(member.guild.id)
    for role in member.roles:
        if role.id in allowed_ids:
            return role
    return None


async def update_nickname(member: discord.Member, reason: str = "Tag update", force: bool = False):
    if member.bot:
        return False

    config = await get_guild_config(member.guild.id)
    if not config:
        return False

    current = member.nick or member.display_name

    # Strip ALL existing tags
    while current.startswith(config["prefix"]):
        suffix_pos = current.find(config["suffix"])
        if suffix_pos == -1:
            break
        current = current[suffix_pos + len(config["suffix"]):].lstrip()

    # ── FIRST-RUN CLEANUP ─────────────────────────────────────────────────
    # Catches any [Whatever] prefix set manually with a different format.
    # Remove after running Refresh All once successfully.
    # current = re.sub(r"^\[.*?\]\s*", "", current).strip()
    # ── END FIRST-RUN CLEANUP ─────────────────────────────────────────────

    tag_role = await get_active_tag_role(member)

    if tag_role:
        proposed = f"{config['prefix']}{tag_role.name}{config['suffix']}{current}"
        if len(proposed) > 32:
            avail = 32 - (len(tag_role.name) + len(config["prefix"]) + len(config["suffix"]))
            proposed = f"{config['prefix']}{tag_role.name}{config['suffix']}{current[:avail].rstrip()}"
        new_nick = proposed
    else:
        new_nick = current

    if new_nick != (member.nick or member.display_name):
        try:
            await member.edit(nick=new_nick[:32], reason=reason)
            logger.info(f"Nickname updated | {member} | '{member.nick or member.display_name}' → '{new_nick}' | Reason: {reason}")
            await log_to_channel(
                member.guild,
                f"✏️ **Nickname Updated**\n"
                f"**User:** {member.mention}\n"
                f"**Before:** `{member.nick or member.display_name}`\n"
                f"**After:** `{new_nick[:32]}`\n"
                f"**Reason:** {reason}",
                LOG_GREEN
            )
            return True
        except Exception as e:
            logger.error(f"Nickname update failed | {member} | {e}")
            await log_to_channel(
                member.guild,
                f"⚠️ **Nickname Update Failed**\n"
                f"**User:** {member.mention}\n"
                f"**Error:** {e}",
                LOG_RED
            )
    return False


# ────────────────────────────────────────────────
#                  CATEGORY SYNC LOGIC
# ────────────────────────────────────────────────

async def sync_category_channels(category: discord.CategoryChannel, excluded_ids: set[int], reason: str = "Category permission sync"):
    synced = 0
    skipped = 0
    for channel in category.channels:
        if channel.id in excluded_ids:
            logger.info(f"Skipping excluded channel #{channel.name} in {category.name}")
            skipped += 1
            continue
        try:
            if not channel.permissions_synced:
                await channel.edit(sync_permissions=True, reason=reason)
                logger.info(f"Synced #{channel.name} → category '{category.name}'")
                await log_to_channel(
                    category.guild,
                    f"🔒 **Channel Synced**\n"
                    f"**Channel:** #{channel.name}\n"
                    f"**Category:** {category.name}\n"
                    f"**Reason:** {reason}",
                    LOG_GREEN
                )
                synced += 1
        except Exception as e:
            logger.error(f"Failed to sync #{channel.name}: {e}")
            await log_to_channel(
                category.guild,
                f"⚠️ **Channel Sync Failed**\n"
                f"**Channel:** #{channel.name}\n"
                f"**Error:** {e}",
                LOG_RED
            )
    return synced, skipped


async def sync_all_categories(guild: discord.Guild, reason: str = "Full category sync"):
    excluded_channel_ids = await get_excluded_channel_ids(guild.id)
    excluded_category_ids = await get_excluded_category_ids(guild.id)
    total_synced = 0
    total_skipped = 0
    for category in guild.categories:
        if category.id in excluded_category_ids:
            logger.info(f"Skipping excluded category: {category.name}")
            total_skipped += len(category.channels)
            continue
        synced, skipped = await sync_category_channels(category, excluded_channel_ids, reason)
        total_synced += synced
        total_skipped += skipped
    return total_synced, total_skipped


# ────────────────────────────────────────────────
#                  PAGINATION HELPER
# ────────────────────────────────────────────────

PAGE_SIZE = 20


def paginate_options(options: list[SelectOption], page: int) -> tuple[list[SelectOption], int]:
    total_pages = max(1, (len(options) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    return options[start:start + PAGE_SIZE], total_pages


# ────────────────────────────────────────────────
#                     VIEWS
# ────────────────────────────────────────────────

class HomeView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Staff Role", style=discord.ButtonStyle.primary, custom_id="home:staff")
    async def staff_button(self, interaction: discord.Interaction, _):
        config = await get_guild_config(interaction.guild.id)
        staff = f"<@&{config['staff_role_id']}>" if config and config.get('staff_role_id') else "Not set"
        embed = discord.Embed(title="Staff Settings", description=f"Current: {staff}", color=0x2ecc71)
        await interaction.response.edit_message(embed=embed, view=StaffView())

    @discord.ui.button(label="Tag Roles", style=discord.ButtonStyle.primary, custom_id="home:tags")
    async def tags_button(self, interaction: discord.Interaction, _):
        embed = discord.Embed(
            title="Tag Roles",
            description="Manage alliance tags",
            color=0xe67e22,
            timestamp=datetime.now(timezone.utc)
        )
        allowed_ids = await get_tag_role_ids(interaction.guild.id)
        current_roles = [interaction.guild.get_role(rid) for rid in allowed_ids if interaction.guild.get_role(rid)]
        await interaction.response.edit_message(embed=embed, view=TagView(interaction.guild, current_roles))

    @discord.ui.button(label="Excluded Channels", style=discord.ButtonStyle.primary, custom_id="home:excluded")
    async def excluded_button(self, interaction: discord.Interaction, _):
        excluded_ids = await get_excluded_channel_ids(interaction.guild.id)
        excluded_cat_ids = await get_excluded_category_ids(interaction.guild.id)
        excluded_channels = [interaction.guild.get_channel(cid) for cid in excluded_ids if interaction.guild.get_channel(cid)]
        excluded_cats = [interaction.guild.get_channel(cid) for cid in excluded_cat_ids if interaction.guild.get_channel(cid)]
        embed = discord.Embed(
            title="Sync Exclusions",
            description="Exclude individual channels or entire categories from permission sync.",
            color=0x9b59b6,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.edit_message(embed=embed, view=ExcludedChannelsView(interaction.guild, excluded_channels, excluded_cats, page=0))

    @discord.ui.button(label="Log Channel", style=discord.ButtonStyle.primary, custom_id="home:log_channel")
    async def log_channel_button(self, interaction: discord.Interaction, _):
        config = await get_guild_config(interaction.guild.id)
        current = f"<#{config['log_channel_id']}>" if config and config.get("log_channel_id") else "Not set"
        embed = discord.Embed(
            title="Log Channel",
            description=f"Current log channel: {current}\n\nSelect a channel below to receive bot activity logs.",
            color=0x1abc9c,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.edit_message(embed=embed, view=LogChannelView(interaction.guild))

    @discord.ui.button(label="Refresh All", style=discord.ButtonStyle.secondary, custom_id="home:refresh_all")
    async def refresh_all(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for member in interaction.guild.members:
            if await update_nickname(member, "Bulk refresh", force=True):
                count += 1
        logger.info(f"Bulk refresh | {interaction.guild.name} | {count} nicknames updated by {interaction.user}")
        await log_to_channel(
            interaction.guild,
            f"🔄 **Bulk Nickname Refresh**\n"
            f"**Triggered by:** {interaction.user.mention}\n"
            f"**Nicknames updated:** {count}",
            LOG_BLUE
        )
        await interaction.followup.send(f"Updated {count} nicknames.", ephemeral=True)

    @discord.ui.button(label="Sync Categories", style=discord.ButtonStyle.secondary, custom_id="home:sync_categories")
    async def sync_categories(self, interaction: discord.Interaction, _):
        await interaction.response.defer(ephemeral=True)
        synced, skipped = await sync_all_categories(interaction.guild, "Manual category sync")
        logger.info(f"Manual category sync | {interaction.guild.name} | {synced} synced, {skipped} skipped by {interaction.user}")
        await log_to_channel(
            interaction.guild,
            f"🔄 **Manual Category Sync**\n"
            f"**Triggered by:** {interaction.user.mention}\n"
            f"**Channels synced:** {synced}\n"
            f"**Skipped (excluded):** {skipped}",
            LOG_BLUE
        )
        await interaction.followup.send(
            f"Synced **{synced}** channels. Skipped **{skipped}** excluded.",
            ephemeral=True
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="home:close_unique")
    async def close(self, interaction: discord.Interaction, _):
        await interaction.response.defer()


class LogChannelView(View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)

        text_channels = sorted(
            [c for c in guild.text_channels],
            key=lambda c: (c.category.name if c.category else "", c.name)
        )
        all_options = [
            SelectOption(
                label=f"#{c.name}"[:100],
                value=str(c.id),
                description=f"Category: {c.category.name if c.category else 'None'}"[:100]
            )
            for c in text_channels
        ]

        self.all_options = all_options
        self.page = 0
        paged_options, self.total_pages = paginate_options(all_options, 0)

        self.channel_select = Select(
            placeholder=f"Select log channel (page 1/{self.total_pages})...",
            custom_id="log:channel_select",
            min_values=1,
            max_values=1,
            options=paged_options or [SelectOption(label="No channels found", value="none")]
        )
        self.channel_select.callback = self.channel_callback
        self.add_item(self.channel_select)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.grey, custom_id="log:prev")
    async def prev_page(self, interaction: discord.Interaction, _):
        if self.page > 0:
            self.page -= 1
            await self._reload(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey, custom_id="log:next")
    async def next_page(self, interaction: discord.Interaction, _):
        if self.page < self.total_pages - 1:
            self.page += 1
            await self._reload(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Clear Log Channel", style=discord.ButtonStyle.red, custom_id="log:clear")
    async def clear_log(self, interaction: discord.Interaction, _):
        await set_log_channel(interaction.guild.id, None)
        logger.info(f"Log channel cleared | {interaction.guild.name} | by {interaction.user}")
        await interaction.response.send_message("✅ Log channel cleared. No logs will be sent.", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, custom_id="log:back")
    async def back(self, interaction: discord.Interaction, _):
        embed = discord.Embed(
            title=f"⚙️ Settings — {interaction.guild.name}",
            description="Navigate using the buttons below:",
            color=0x5865f2
        )
        await interaction.response.edit_message(embed=embed, view=HomeView())

    async def channel_callback(self, interaction: discord.Interaction):
        value = self.channel_select.values[0]
        if value == "none":
            await interaction.response.send_message("No channels available.", ephemeral=True)
            return
        try:
            channel_id = int(value)
            await set_log_channel(interaction.guild.id, channel_id)
            channel = interaction.guild.get_channel(channel_id)
            logger.info(f"Log channel set | {interaction.guild.name} | #{channel.name} | by {interaction.user}")
            await interaction.response.send_message(
                f"✅ Log channel set to {channel.mention}", ephemeral=True
            )
            await log_to_channel(
                interaction.guild,
                f"📋 **Log Channel Configured**\n"
                f"**Channel:** {channel.mention}\n"
                f"**Set by:** {interaction.user.mention}\n"
                f"Bot activity will now be logged here.",
                LOG_BLUE
            )
        except Exception as e:
            logger.error(f"Set log channel failed: {e}")
            await interaction.response.send_message("Failed to set log channel.", ephemeral=True)

    async def _reload(self, interaction: discord.Interaction):
        paged_options, self.total_pages = paginate_options(self.all_options, self.page)
        self.channel_select.placeholder = f"Select log channel (page {self.page + 1}/{self.total_pages})..."
        self.channel_select.options = paged_options
        config = await get_guild_config(interaction.guild.id)
        current = f"<#{config['log_channel_id']}>" if config and config.get("log_channel_id") else "Not set"
        embed = discord.Embed(
            title="Log Channel",
            description=f"Current log channel: {current}\n\nSelect a channel below to receive bot activity logs.",
            color=0x1abc9c,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.edit_message(embed=embed, view=self)


class ExcludedChannelsView(View):
    def __init__(self, guild: discord.Guild, excluded_channels: list, excluded_cats: list, page: int = 0):
        super().__init__(timeout=180)
        self.guild = guild
        self.excluded_channels = excluded_channels
        self.excluded_cats = excluded_cats
        self.page = page

        all_channels = sorted(
            [c for c in guild.channels if not isinstance(c, discord.CategoryChannel)],
            key=lambda c: (c.category.name if c.category else "", c.name)
        )
        all_channel_options = [
            SelectOption(
                label=f"#{c.name}"[:100],
                value=str(c.id),
                description=f"Category: {c.category.name if c.category else 'None'}"[:100]
            )
            for c in all_channels
        ]

        paged_options, self.total_pages = paginate_options(all_channel_options, page)

        self.add_select = Select(
            placeholder=f"Exclude channel (page {page + 1}/{self.total_pages})...",
            custom_id="excluded:add_select",
            min_values=1,
            max_values=1,
            options=paged_options
        )
        self.add_select.callback = self.add_channel_callback
        self.add_item(self.add_select)

        remove_ch_options = [
            SelectOption(
                label=f"#{c.name}"[:100],
                value=str(c.id),
                description=f"Category: {c.category.name if c.category else 'None'}"[:100]
            )
            for c in excluded_channels
        ] or [SelectOption(label="No excluded channels", value="none")]

        self.remove_ch_select = Select(
            placeholder="Remove channel exclusion...",
            custom_id="excluded:remove_ch_select",
            min_values=1,
            max_values=1,
            options=remove_ch_options
        )
        self.remove_ch_select.callback = self.remove_channel_callback
        self.add_item(self.remove_ch_select)

        cat_options = [
            SelectOption(
                label=cat.name[:100],
                value=str(cat.id),
                description=f"{len(cat.channels)} channels"
            )
            for cat in guild.categories
        ] or [SelectOption(label="No categories found", value="none")]

        self.add_cat_select = Select(
            placeholder="Exclude entire category...",
            custom_id="excluded:add_cat_select",
            min_values=1,
            max_values=1,
            options=cat_options[:25]
        )
        self.add_cat_select.callback = self.add_category_callback
        self.add_item(self.add_cat_select)

        remove_cat_options = [
            SelectOption(
                label=cat.name[:100],
                value=str(cat.id),
                description=f"{len(cat.channels)} channels"
            )
            for cat in excluded_cats if cat is not None
        ] or [SelectOption(label="No excluded categories", value="none")]

        self.remove_cat_select = Select(
            placeholder="Remove category exclusion...",
            custom_id="excluded:remove_cat_select",
            min_values=1,
            max_values=1,
            options=remove_cat_options
        )
        self.remove_cat_select.callback = self.remove_category_callback
        self.add_item(self.remove_cat_select)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.grey, custom_id="excluded:prev")
    async def prev_page(self, interaction: discord.Interaction, _):
        if self.page > 0:
            await self._reload(interaction, self.page - 1)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey, custom_id="excluded:next")
    async def next_page(self, interaction: discord.Interaction, _):
        if self.page < self.total_pages - 1:
            await self._reload(interaction, self.page + 1)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="List All Exclusions", style=discord.ButtonStyle.blurple, custom_id="excluded:list")
    async def list_excluded(self, interaction: discord.Interaction, _):
        excluded_ids = await get_excluded_channel_ids(interaction.guild.id)
        excluded_cat_ids = await get_excluded_category_ids(interaction.guild.id)
        channels = [interaction.guild.get_channel(cid) for cid in excluded_ids if interaction.guild.get_channel(cid)]
        cats = [interaction.guild.get_channel(cid) for cid in excluded_cat_ids if interaction.guild.get_channel(cid)]
        ch_list = "\n".join(f"- #{c.name}" for c in channels) or "None"
        cat_list = "\n".join(f"- {c.name}" for c in cats) or "None"
        await interaction.response.send_message(
            f"**Excluded Channels:**\n{ch_list}\n\n**Excluded Categories:**\n{cat_list}",
            ephemeral=True
        )

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, custom_id="excluded:back")
    async def back(self, interaction: discord.Interaction, _):
        embed = discord.Embed(
            title=f"⚙️ Settings — {interaction.guild.name}",
            description="Navigate using the buttons below:",
            color=0x5865f2
        )
        await interaction.response.edit_message(embed=embed, view=HomeView())

    async def add_channel_callback(self, interaction: discord.Interaction):
        value = self.add_select.values[0]
        if value == "none":
            await interaction.response.send_message("No channels available.", ephemeral=True)
            return
        try:
            channel_id = int(value)
            await add_excluded_channel(interaction.guild.id, channel_id)
            channel = interaction.guild.get_channel(channel_id)
            name = channel.name if channel else "Unknown"
            logger.info(f"Channel excluded from sync | #{name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"🚫 **Channel Excluded from Sync**\n"
                f"**Channel:** #{name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_YELLOW
            )
            await interaction.response.send_message(f"✅ **#{name}** excluded from sync.", ephemeral=True)
        except Exception as e:
            logger.error(f"Exclude channel failed: {e}")
            await interaction.response.send_message("Failed to exclude channel.", ephemeral=True)

    async def remove_channel_callback(self, interaction: discord.Interaction):
        value = self.remove_ch_select.values[0]
        if value == "none":
            await interaction.response.send_message("No exclusions to remove.", ephemeral=True)
            return
        try:
            channel_id = int(value)
            await remove_excluded_channel(interaction.guild.id, channel_id)
            channel = interaction.guild.get_channel(channel_id)
            name = channel.name if channel else "Unknown"
            logger.info(f"Channel exclusion removed | #{name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"✅ **Channel Exclusion Removed**\n"
                f"**Channel:** #{name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_GREEN
            )
            await interaction.response.send_message(f"✅ **#{name}** will now be included in sync.", ephemeral=True)
        except Exception as e:
            logger.error(f"Remove channel exclusion failed: {e}")
            await interaction.response.send_message("Failed to remove exclusion.", ephemeral=True)

    async def add_category_callback(self, interaction: discord.Interaction):
        value = self.add_cat_select.values[0]
        if value == "none":
            await interaction.response.send_message("No categories available.", ephemeral=True)
            return
        try:
            category_id = int(value)
            await add_excluded_category(interaction.guild.id, category_id)
            cat = interaction.guild.get_channel(category_id)
            name = cat.name if cat else "Unknown"
            logger.info(f"Category excluded from sync | {name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"🚫 **Category Excluded from Sync**\n"
                f"**Category:** {name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_YELLOW
            )
            await interaction.response.send_message(f"✅ Category **{name}** excluded from sync.", ephemeral=True)
        except Exception as e:
            logger.error(f"Exclude category failed: {e}")
            await interaction.response.send_message("Failed to exclude category.", ephemeral=True)

    async def remove_category_callback(self, interaction: discord.Interaction):
        value = self.remove_cat_select.values[0]
        if value == "none":
            await interaction.response.send_message("No category exclusions to remove.", ephemeral=True)
            return
        try:
            category_id = int(value)
            await remove_excluded_category(interaction.guild.id, category_id)
            cat = interaction.guild.get_channel(category_id)
            name = cat.name if cat else "Unknown"
            logger.info(f"Category exclusion removed | {name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"✅ **Category Exclusion Removed**\n"
                f"**Category:** {name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_GREEN
            )
            await interaction.response.send_message(f"✅ Category **{name}** will now be synced.", ephemeral=True)
        except Exception as e:
            logger.error(f"Remove category exclusion failed: {e}")
            await interaction.response.send_message("Failed to remove category exclusion.", ephemeral=True)

    async def _reload(self, interaction: discord.Interaction, new_page: int):
        excluded_ids = await get_excluded_channel_ids(interaction.guild.id)
        excluded_cat_ids = await get_excluded_category_ids(interaction.guild.id)
        excluded_channels = [interaction.guild.get_channel(cid) for cid in excluded_ids if interaction.guild.get_channel(cid)]
        excluded_cats = [interaction.guild.get_channel(cid) for cid in excluded_cat_ids if interaction.guild.get_channel(cid)]
        embed = discord.Embed(
            title="Sync Exclusions",
            description="Exclude individual channels or entire categories from permission sync.",
            color=0x9b59b6,
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.edit_message(
            embed=embed,
            view=ExcludedChannelsView(interaction.guild, excluded_channels, excluded_cats, page=new_page)
        )


class StaffView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Set Staff Role", style=discord.ButtonStyle.green, custom_id="staff:set")
    async def set_staff(self, interaction: discord.Interaction, _):
        try:
            await interaction.response.send_modal(StaffModal())
        except Exception as e:
            logger.error(f"Modal send failed: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("Failed to open modal.", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, custom_id="staff:back_unique")
    async def back(self, interaction: discord.Interaction, _):
        embed = discord.Embed(title=f"⚙️ Settings — {interaction.guild.name}", description="...", color=0x5865f2)
        await interaction.response.edit_message(embed=embed, view=HomeView())


class StaffModal(Modal, title="Set Staff Role"):
    role_id_input = TextInput(
        label="Staff Role ID",
        placeholder="Right-click role → Copy Role ID → paste here",
        style=discord.TextStyle.short,
        required=True,
        min_length=17,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            role_id = int(self.role_id_input.value.strip())
            role = interaction.guild.get_role(role_id)
            if not role:
                raise ValueError("Role not found")
            await set_staff_role(interaction.guild.id, role_id)
            logger.info(f"Staff role set | {role.name} ({role_id}) | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"⚙️ **Staff Role Updated**\n"
                f"**Role:** {role.mention}\n"
                f"**By:** {interaction.user.mention}",
                LOG_BLUE
            )
            await interaction.response.send_message(f"✅ Staff role set to **{role.name}** (`{role_id}`)", ephemeral=True)
        except ValueError as ve:
            await interaction.response.send_message(f"Invalid: {str(ve)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Modal submit failed: {e}")
            await interaction.response.send_message("Error saving role.", ephemeral=True)


class TagView(View):
    def __init__(self, guild: discord.Guild, current_roles: list[discord.Role]):
        super().__init__(timeout=180)

        add_options = []
        for role in guild.roles:
            if role.name.strip() and len(role.name) <= 100:
                if role.is_default() or role.managed:
                    continue
                add_options.append(
                    SelectOption(
                        label=role.name,
                        value=str(role.id),
                        description=f"Members: {len(role.members)}"
                    )
                )
        add_options = add_options[:25] or [SelectOption(label="No roles to add", value="none")]

        self.add_select = Select(
            placeholder="Add role as tag...",
            custom_id="tag:add_select_unique",
            min_values=1,
            max_values=1,
            options=add_options
        )
        self.add_select.callback = self.add_callback
        self.add_item(self.add_select)

        remove_options = [
            SelectOption(label=role.name, value=str(role.id), description=f"Remove {role.name}")
            for role in current_roles
        ] or [SelectOption(label="No tag roles to remove", value="none")]

        self.remove_select = Select(
            placeholder="Remove tag role...",
            custom_id="tag:remove_select_unique",
            min_values=1,
            max_values=1,
            options=remove_options
        )
        self.remove_select.callback = self.remove_callback
        self.add_item(self.remove_select)

    async def add_callback(self, interaction: discord.Interaction):
        value = self.add_select.values[0]
        if value == "none":
            await interaction.response.send_message("No roles to add.", ephemeral=True)
            return
        try:
            role_id = int(value)
            await add_tag_role(interaction.guild.id, role_id)
            role = interaction.guild.get_role(role_id)
            name = role.name if role else "Unknown"
            logger.info(f"Tag role added | {name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"🏷️ **Tag Role Added**\n"
                f"**Role:** {role.mention if role else name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_GREEN
            )
            await interaction.response.send_message(f"Added **{name}** as tag role", ephemeral=True)
        except Exception as e:
            logger.error(f"Add tag role failed: {e}")
            await interaction.response.send_message("Failed to add role.", ephemeral=True)

    async def remove_callback(self, interaction: discord.Interaction):
        value = self.remove_select.values[0]
        if value == "none":
            await interaction.response.send_message("No tag roles to remove.", ephemeral=True)
            return
        try:
            role_id = int(value)
            await remove_tag_role(interaction.guild.id, role_id)
            role = interaction.guild.get_role(role_id)
            name = role.name if role else "Unknown"
            logger.info(f"Tag role removed | {name} | {interaction.guild.name} | by {interaction.user}")
            await log_to_channel(
                interaction.guild,
                f"🏷️ **Tag Role Removed**\n"
                f"**Role:** {name}\n"
                f"**By:** {interaction.user.mention}",
                LOG_RED
            )
            await interaction.response.send_message(f"Removed **{name}** from tag roles", ephemeral=True)
        except Exception as e:
            logger.error(f"Remove tag role failed: {e}")
            await interaction.response.send_message("Failed to remove role.", ephemeral=True)

    @discord.ui.button(label="List Current Tags", style=discord.ButtonStyle.blurple, custom_id="tag:list_current_unique")
    async def list_tags(self, interaction: discord.Interaction, _):
        allowed_ids = await get_tag_role_ids(interaction.guild.id)
        roles = [interaction.guild.get_role(rid) for rid in allowed_ids if interaction.guild.get_role(rid)]
        content = "Current tag roles:\n" + ("\n".join(f"- {r.name}" for r in roles) or "None set")
        await interaction.response.send_message(content, ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.grey, custom_id="tag:back_unique")
    async def back(self, interaction: discord.Interaction, _):
        embed = discord.Embed(title=f"⚙️ Settings — {interaction.guild.name}", description="...", color=0x5865f2)
        await interaction.response.edit_message(embed=embed, view=HomeView())


# ────────────────────────────────────────────────
#                     EVENTS & COMMANDS
# ────────────────────────────────────────────────

@bot.event
async def on_ready():
    await init_db()
    logger.info(f"Logged in as {bot.user}")
    bot.add_view(HomeView())
    bot.add_view(StaffView())
    await tree.sync()
    logger.info("Command tree synced — Ready")


@bot.event
async def on_guild_join(guild):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (guild.id,))
        await db.commit()
    logger.info(f"Joined guild: {guild.name} ({guild.id})")


@bot.event
async def on_member_join(member):
    logger.info(f"Member joined | {member} | {member.guild.name}")
    await update_nickname(member, reason="Member joined")


@bot.event
async def on_member_update(before, after):
    if set(r.id for r in before.roles) != set(r.id for r in after.roles):
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added:
            logger.info(f"Role added | {after} | {[r.name for r in added]} | {after.guild.name}")
        if removed:
            logger.info(f"Role removed | {after} | {[r.name for r in removed]} | {after.guild.name}")
        await update_nickname(after, reason="Role change")


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if not isinstance(after, discord.CategoryChannel):
        return
    if before.overwrites == after.overwrites:
        return

    excluded_cat_ids = await get_excluded_category_ids(after.guild.id)
    if after.id in excluded_cat_ids:
        logger.info(f"Category '{after.name}' is excluded — skipping auto-sync")
        return

    logger.info(f"Category permissions changed | '{after.name}' | {after.guild.name} — auto-syncing")
    excluded_ids = await get_excluded_channel_ids(after.guild.id)
    synced, skipped = await sync_category_channels(after, excluded_ids, f"Auto-sync: category '{after.name}' updated")
    logger.info(f"Auto-sync complete | '{after.name}' | {synced} synced, {skipped} skipped")
    await log_to_channel(
        after.guild,
        f"🔒 **Auto Category Sync**\n"
        f"**Category:** {after.name}\n"
        f"**Channels synced:** {synced}\n"
        f"**Skipped (excluded):** {skipped}",
        LOG_BLUE
    )


@tree.command(name="role_settings", description="Open role & tag settings (staff only)")
async def role_settings(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Only in servers", ephemeral=True)

    config = await get_guild_config(interaction.guild.id)

    if not config or not config.get("staff_role_id"):
        embed = discord.Embed(title="Initial Setup Required", description="Please set the Staff role first.", color=0xff0000)
        return await interaction.response.send_message(embed=embed, view=StaffView(), ephemeral=True)

    if not any(r.id == config["staff_role_id"] for r in interaction.user.roles):
        return await interaction.response.send_message("Staff only.", ephemeral=True)

    logger.info(f"Settings opened | {interaction.guild.name} | by {interaction.user}")
    embed = discord.Embed(
        title=f"⚙️ {interaction.guild.name} Settings",
        description="Navigate using the buttons below:",
        color=0x5865f2,
        timestamp=datetime.now(timezone.utc)
    )
    await interaction.response.send_message(embed=embed, view=HomeView(), ephemeral=True)


bot.run(TOKEN)