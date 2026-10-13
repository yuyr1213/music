import os
import asyncio
import random
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

ytdl_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_options)

# 讀取 playlist.txt 內的網址清單
def load_playlist_urls():
    if not os.path.exists('playlist.txt'):
        return []
    
    with open('playlist.txt', 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    return urls

# 自動將新點的歌曲網址寫入 playlist.txt（避免重複）
def append_url_to_playlist(url):
    if not url:
        return
    existing_urls = load_playlist_urls()
    clean_url = url.split('&')[0]
    
    is_exist = any(clean_url in item for item in existing_urls)
    if not is_exist:
        with open('playlist.txt', 'a', encoding='utf-8') as f:
            f.write(f"{url}\n")
        print(f"📥 已自動將新歌加入 playlist.txt: {url}")

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def create_source(cls, search, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
        
        if data and 'entries' in data:
            entries = data['entries']
            if len(entries) > 0:
                data = entries[0]
            else:
                raise Exception("找不到相關音樂")

        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class MusicManager:
    def __init__(self):
        self.user_queue = []     
        self.text_channel = None

guild_managers = {}

def get_manager(guild_id):
    if guild_id not in guild_managers:
        guild_managers[guild_id] = MusicManager()
    return guild_managers[guild_id]

async def music_player_loop(guild):
    manager = get_manager(guild.id)
    
    while True:
        player_to_play = None
        title_to_show = ""
        source_type = ""

        # 1. 優先播放使用者手動點的歌
        if len(manager.user_queue) > 0:
            player_to_play, title_to_show = manager.user_queue.pop(0)
            source_type = "使用者點歌"
        else:
            # 2. 沒人點歌時，從 playlist.txt 隨機抽一首
            playlist_urls = load_playlist_urls()
            if len(playlist_urls) > 0:
                random_url = random.choice(playlist_urls)
                try:
                    print(f"從 playlist.txt 隨機抽取網址播放: {random_url}")
                    player_to_play = await YTDLSource.create_source(random_url, loop=bot.loop)
                    title_to_show = player_to_play.title
                    source_type = "自訂清單隨機播放"
                except Exception as e:
                    print(f"播放清單網址失敗: {e}")
                    await asyncio.sleep(3)
                    continue
            else:
                try:
                    player_to_play = await YTDLSource.create_source("Lo-fi beats", loop=bot.loop)
                    title_to_show = player_to_play.title
                    source_type = "備用隨機播放"
                except:
                    await asyncio.sleep(3)
                    continue

        if manager.text_channel and player_to_play:
            try:
                prefix = "🎶 正在播放（點歌）：" if source_type == "使用者點歌" else "📻 隨機播放（你的歌單）："
                await manager.text_channel.send(f"{prefix} **{title_to_show}**")
            except:
                pass

        loop = asyncio.get_running_loop()
        play_next_event = asyncio.Event()

        def after_playing(error):
            if error:
                print(f"播放發生錯誤: {error}")
            loop.call_soon_threadsafe(play_next_event.set)

        if guild.voice_client and guild.voice_client.is_connected():
            guild.voice_client.play(player_to_play, after=after_playing)
            await play_next_event.wait()
        else:
            break

@bot.event
async def on_ready():
    print(f'機器人已成功上線：{bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'已同步 {len(synced)} 個 Slash 指令')
    except Exception as e:
        print(e)

@bot.tree.command(name="play", description="點播指定歌曲（會自動加入歌單並插隊播放）")
async def play(interaction: discord.Interaction, search: str):
    if not interaction.user.voice:
        await interaction.response.send_message("請先加入語音頻道！", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    voice_channel = interaction.user.voice.channel
    guild = interaction.guild
    manager = get_manager(guild.id)
    manager.text_channel = interaction.channel

    if guild.voice_client is None:
        try:
            await voice_channel.connect()
        except Exception as e:
            await interaction.followup.send(f"無法加入語音頻道：{e}")
            return

    try:
        player = await YTDLSource.create_source(search, loop=bot.loop)
        
        song_url = player.webpage_url or getattr(player, 'url', None)
        if song_url:
            append_url_to_playlist(song_url)

        manager.user_queue.append((player, player.title))
        await interaction.followup.send(f"📥 已加入點歌排隊並收錄至歌單：**{player.title}** (目前排隊第 {len(manager.user_queue)} 首)")

        if not guild.voice_client.is_playing() and not guild.voice_client.is_paused():
            bot.loop.create_task(music_player_loop(guild))

    except Exception as e:
        await interaction.followup.send(f"點歌時發生錯誤：$e")

@bot.tree.command(name="list", description="查看目前手動點歌的排隊清單")
async def show_list(interaction: discord.Interaction):
    guild = interaction.guild
    manager = get_manager(guild.id)
    
    if not manager.user_queue:
        await interaction.response.send_message("📂 目前沒有人手動點歌排隊！", ephemeral=True)
        return

    msg = "📜 **目前手動點歌排隊清單**:\n"
    for idx, (_, title) in enumerate(manager.user_queue, 1):
        msg += f"{idx}. {title}\n"

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="skip", description="強制跳過當前歌曲")
async def skip(interaction: discord.Interaction):
    guild = interaction.guild
    if guild.voice_client and (guild.voice_client.is_playing() or guild.voice_client.is_paused()):
        guild.voice_client.stop() 
        await interaction.response.send_message("⏭️ 已強制跳過當前歌曲！")
    else:
        await interaction.response.send_message("目前沒有正在播放的音樂。", ephemeral=True)

@bot.tree.command(name="leave", description="讓機器人離開語音頻道")
async def leave(interaction: discord.Interaction):
    guild = interaction.guild
    manager = get_manager(guild.id)
    manager.user_queue.clear()
    
    if guild.voice_client:
        if guild.voice_client.is_playing():
            guild.voice_client.stop()
        await guild.voice_client.disconnect()
        await interaction.response.send_message("👋 已離開語音頻道並清除狀態。")
    else:
        await interaction.response.send_message("機器人目前不在語音頻道中。", ephemeral=True)

bot.run(TOKEN)
