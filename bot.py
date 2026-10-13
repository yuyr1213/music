import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': 'True'
}

last_played_titles = {}

# 建立音樂控制按鈕介面 (View)
class MusicControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="暫停 / 繼續", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("⚠️ 機器人目前不在語音頻道中！", ephemeral=True)
            return
        
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ 音樂已暫停", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ 音樂已繼續播放", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 目前沒有在播放音樂", ephemeral=True)

    @discord.ui.button(label="下一首 (Skip)", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ 已跳過，正在為您切換下一首！", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 目前沒有正在播放的音樂。", ephemeral=True)

    @discord.ui.button(label="關閉離開", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            await interaction.response.send_message("👋 已停止音樂並離開語音頻道！", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 機器人目前不在語音頻道中。", ephemeral=True)

def play_auto_next(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client

    if not vc or not vc.is_connected():
        return

    prev_title = last_played_titles.get(guild_id, "popular music")
    auto_query = f"ytsearch:best songs similar to {prev_title}"

    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(auto_query, download=False)
            if 'entries' in info and len(info['entries']) > 0:
                entry = info['entries'][0]
                url = entry['url']
                title = entry.get('title', '未知推薦歌曲')
                
                last_played_titles[guild_id] = title

                def after_playing(error):
                    if error:
                        print(f"播放發生錯誤: {error}")
                    play_auto_next(interaction)

                vc.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS), after=after_playing)
                
                view = MusicControlView()
                asyncio.run_coroutine_threadsafe(
                    interaction.channel.send(f"🔀 **[自動續播]** 正在播放推薦：**{title}**", view=view), 
                    bot.loop
                )
    except Exception as e:
        print(f"自動續播錯誤: {e}")

@bot.event
async def on_ready():
    print(f'✅ 機器人已成功上線：{bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"🔄 已同步 {len(synced)} 個 Slash 指令")
    except Exception as e:
        print(e)

@bot.tree.command(name="play", description="播放音樂 (支援歌名或網址，並具備全自動續播與按鈕面板)")
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ 請先加入語音頻道再點歌！", ephemeral=True)
        return

    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel

    vc = interaction.guild.voice_client
    if not vc:
        vc = await voice_channel.connect()

    if query.startswith("http://") or query.startswith("https://"):
        search_query = query
    else:
        search_query = f"ytsearch:{query}"

    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            url = info['url']
            title = info.get('title', '未知歌曲')
    except Exception as e:
        print(f"解析錯誤: {e}")
        await interaction.followup.send("⚠️ 找不到這首歌或該連結無法解析！")
        return

    guild_id = interaction.guild.id
    last_played_titles[guild_id] = title

    def after_playing(error):
        if error:
            print(f"播放發生錯誤: {error}")
        play_auto_next(interaction)

    if vc.is_playing() or vc.is_paused():
        vc.stop()

    vc.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS), after=after_playing)
    
    view = MusicControlView()
    await interaction.followup.send(f"🎵 正在播放：**{title}** (✨ 全自動續播中)", view=view)

@bot.tree.command(name="leave", description="讓機器人離開語音頻道")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 已離開語音頻道！")
    else:
        await interaction.response.send_message("⚠️ 機器人目前不在語音頻道中。", ephemeral=True)

bot.run(TOKEN)