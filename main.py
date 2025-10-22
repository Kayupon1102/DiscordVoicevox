import subprocess
from discord.opus import Encoder
import shlex
import io
import json
import voicevox_core
from pathlib import Path
import discord
from discord import app_commands
from typing import Pattern
import sys
import re
import random
from pydub import AudioSegment

class FFmpegPCMAudio(discord.AudioSource):
    def __init__(self, source, *, executable='ffmpeg', pipe=False, stderr=None, before_options=None, options=None):
        stdin = None if not pipe else source
        args = [executable]
        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))
        args.append('-i')
        args.append('-' if pipe else source)
        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning'))
        if isinstance(options, str):
            args.extend(shlex.split(options))
        args.append('pipe:1')
        self._process = None
        self._frame_byte_size = Encoder.FRAME_SIZE * 4
        try:
            self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
            self._stdout = io.BytesIO(
                self._process.communicate(input=stdin)[0]
            )
        except FileNotFoundError:
            raise discord.ClientException(executable + ' was not found.') from None
        except subprocess.SubprocessError as exc:
            raise discord.ClientException('Popen failed: {0.__class__.__name__}: {0}'.format(exc)) from exc
    def read(self):
        ret = self._stdout.read(self._frame_byte_size)
        if len(ret) != self._frame_byte_size:
            return b''
        return ret
    def cleanup(self):
        proc = self._process
        if proc is None:
            return
        proc.kill()
        if proc.poll() is None:
            proc.communicate()

        self._process = None

client = discord.Client(intents=discord.Intents.all())
tree = app_commands.CommandTree(client)
guild_ids: list[int] = []
guild_objects: list[discord.Object] = []
voiceSource: dict[str,list] = {}
wordDictionary: dict[str,dict[str,str]] = {}
patternDictionary: dict[str,dict[str,Pattern]] = {}
URL_PATTERN = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
EMOJI_PATTERN = re.compile(r"(?:<:[a-zA-Z0-9]+:[0-9]+>)+")
MENTION_PATTERN = re.compile(r"<@[0-9]+>")
userSetting = {}
botSetting = {}

def mix_audio(byte_list):
    if not byte_list:
        raise ValueError("Input list must contain at least one audio file.")
    
    # 最初の音声データをAudioSegmentに変換
    mixed_audio = AudioSegment.from_wav(io.BytesIO(byte_list[0]))

    # 残りの音声データを順番にミックス
    for byte_data in byte_list[1:]:
        audio = AudioSegment.from_wav(io.BytesIO(byte_data))
        mixed_audio = mixed_audio.overlay(audio)
    
    # ミックスした音声を新しいバイトデータとして保存
    mixed_wave = io.BytesIO()
    mixed_audio.export(mixed_wave, format="wav")
    
    # ミックスした音声データを返す
    return mixed_wave.getvalue()

def connect_audio(byte_list, gap=0):
    if not byte_list:
        raise ValueError("Input list must contain at least one audio file.")
    
    # 最初の音声データをAudioSegmentに変換
    connected_audio = AudioSegment.from_wav(io.BytesIO(byte_list[0]))

    # 残りの音声データを順番に接続
    for byte_data in byte_list[1:]:
        audio = AudioSegment.from_wav(io.BytesIO(byte_data))
        connected_audio = connected_audio + AudioSegment.silent(duration=gap) + audio

    # 接続した音声を新しいバイトデータとして保存
    connected_wave = io.BytesIO()
    connected_audio.export(connected_wave, format="wav")
    
    # 接続した音声データを返す
    return connected_wave.getvalue()


def speakerIDList():
    tmp = ""
    for speaker in voicevox_core.METAS:
        tmp += speaker.name + "\n"
        for style in speaker.styles:
            id = style.id
            name = style.name
            tmp += f"{str(id):>5}:   {name}\n"
        tmp += "\n"
    return tmp

def speakerIDtoName(id: int):
    for speaker in voicevox_core.METAS:
        for style in speaker.styles:
            if style.id == id:
                return speaker.name+"("+style.name+")"
    return None

with open("botSetting.json") as f:
    string = f.read()
    if string != "":
        botSetting = json.loads(string)
        for raw_id in botSetting["guildIDs"]:
            guild_id = int(raw_id)
            guild_ids.append(guild_id)
            guild_objects.append(discord.Object(id=guild_id))

with open("userSetting.json") as f:
    string = f.read()
    if string != "":
        userSetting = json.loads(string)

with open("dict.json") as f:
    string = f.read()
    if string != "":
        wordDictionary = json.loads(string)
        for guildID in wordDictionary.keys():
            patternDictionary[guildID] = {}
            for word in wordDictionary[guildID].keys():
                try:
                    patternDictionary[guildID][word] = re.compile(word)
                except re.error:
                    print(f"正規表現のコンパイルに失敗しました。({word})")

core = voicevox_core.VoicevoxCore(open_jtalk_dict_dir=Path(botSetting["jtalkPath"]))

@app_commands.command(
    name="texvoice",
    description="Voiceの選択"
)
@app_commands.guilds(*guild_ids)
async def setSpeakerID(ctx: discord.Interaction, voiceid: str = None):
    userid = str(ctx.user.id)
    guildid = str(ctx.guild_id)
    if guildid not in userSetting:
        userSetting[guildid] = {}
        
    if guildid not in voiceSource:
        voiceSource[guildid] = []

    if voiceid is None:
        if userid not in userSetting[guildid]:
            await ctx.response.send_message("SpeakerIDが登録されていません。\n`/texvoice [数字]`で指定できます。\n`/speakerlist` でIDの一覧を表示できます。", ephemeral=True)
        else:
            await ctx.response.send_message("あなたのSpeakerIDは`"+str(userSetting[guildid][userid]["voiceid"])+":"+speakerIDtoName(int(userSetting[guildid][userid]["voiceid"]))+"`です。\n`/texvoice [数字]`で変更できます。\n`/speakerlist` でIDの一覧を表示できます。", ephemeral=True)

    else:
        if speakerIDtoName(int(voiceid)) is None:
            await ctx.response.send_message(f"`{voiceid}`はリストに含まれません。\n`/speakerlist` でIDの一覧を表示できます。",ephemeral=True)
            return
        await ctx.response.send_message(f"OK\n{ctx.user.display_name}さんの声は`{voiceid}: {speakerIDtoName(int(voiceid))}`に指定されました。")
        if userid not in userSetting[guildid]:
            userSetting[guildid][userid] = {}
        userSetting[guildid][userid]["voiceid"] = voiceid
        userSetting[guildid][userid]["name"] = ctx.user.display_name
        with open("userSetting.json", "w") as f:
            f.write(json.dumps(userSetting))


@app_commands.command(
    name="join",
    description="TextVoiceを通話に参加させます。"
)
@app_commands.guilds(*guild_ids)
async def join(ctx: discord.Interaction):
    if ctx.user.voice is None:
        await ctx.response.send_message("あなたはVoiceチャンネルに接続していません。",ephemeral=True)
        return
    if ctx.guild.voice_client is not None:
        await ctx.response.send_message("私は既にVoiceチャンネルに接続しています。",ephemeral=True)
        return
    voiceSource.setdefault(str(ctx.guild_id), [])
    await ctx.user.voice.channel.connect(timeout=10)
    await ctx.response.send_message("接続しました。",ephemeral=True)

@app_commands.command(
    name="left",
    description="TextVoiceを通話から切断します。"
)
@app_commands.guilds(*guild_ids)
async def left(ctx: discord.Interaction):
    if ctx.guild.voice_client is None:
        await ctx.response.send_message("私はVoiceチャンネルに接続していません。",ephemeral=True)
        return
    if ctx.user.voice is None:
        await ctx.response.send_message("あなたはVoiceチャンネルに接続していません。\nボイスチャンネルにいる人が切断できます。",ephemeral=True)
        return
    await ctx.guild.voice_client.disconnect()
    await ctx.response.send_message("切断しました。",ephemeral=True)

@app_commands.command(
    name="speakerlist",
    description="話者IDの一覧を表示します。"
)
@app_commands.guilds(*guild_ids)
async def speakerList(ctx:discord.Interaction):
    await ctx.response.send_message(f"```\n{speakerIDList()}\n```",ephemeral=True)

@app_commands.command(
    name="dictionary",
    description="辞書に登録、削除ができます。"
)
@app_commands.guilds(*guild_ids)
async def dictionary(ctx:discord.Interaction, key:str, value:str = None):
    guildid = str(ctx.guild.id)

    if ctx.channel_id not in botSetting.get("channelIDs", []):
        await ctx.response.send_message("このチャンネルでは使用できません。",ephemeral=True)
        return

    if guildid not in wordDictionary:
        wordDictionary[guildid] = {}
    if guildid not in patternDictionary:
        patternDictionary[guildid] = {}

    if value is None:
        if key not in wordDictionary[guildid]:
            await ctx.response.send_message(f"`{key}`は登録されていません。")
        else:
            del wordDictionary[guildid][key]
            patternDictionary[guildid].pop(key, None)
            await ctx.response.send_message(f"`{key}`を削除しました。")
    else:
        if re.match("^[ぁ-んァ-ンー　\s]+$", value):
            try:
                patternDictionary[guildid][key] = re.compile(key)
                wordDictionary[guildid][key] = value
                await ctx.response.send_message(f"`{key}`は`{value}`と発音されます。")
            except re.error:
                await ctx.response.send_message(f"`{key}` に構文エラーがあります。")
                return
        else:
            await ctx.response.send_message(f"`{value}`<<<読み方には平仮名か片仮名のみが指定できます。")

    with open("dict.json", "w") as f:
        f.write(json.dumps(wordDictionary))

#dictionaryの一覧を返信するコマンド
@app_commands.command(
    name="dictlist",
    description="辞書の一覧を表示します。"
)
@app_commands.guilds(*guild_ids)
async def dictList(ctx:discord.Interaction):
    guildid = str(ctx.guild.id)
    if guildid not in wordDictionary:
        await ctx.response.send_message("辞書に何も登録されていません。")
        return
    dictString :str = "```"
    for key in wordDictionary[guildid].keys():
        dictString += f"{key} : {wordDictionary[guildid][key]}\n"
    dictString += "```"
    await ctx.response.send_message(dictString,ephemeral=True)


for command in (setSpeakerID, join, left, speakerList, dictionary, dictList):
    tree.add_command(command)


@client.event
async def on_ready() -> None:
    print("on_ready", discord.__version__)

    registered = [cmd.name for cmd in tree.get_commands()]
    print(f"[tree] registered commands: {registered}")

    # 1) ギルド同期（開発用: 即反映）
    total_guild_synced = 0
    for g in guild_objects:
        try:
            synced = await tree.sync(guild=g)
            print(f"[guild {g.id}] synced: {[getattr(c, 'name', repr(c)) for c in synced]}")
            total_guild_synced += len(synced)
        except discord.HTTPException as e:
            print(f"Failed to sync commands for guild {getattr(g, 'id', '?')}: {e}")

    # 2) グローバル同期（指定ギルドが空、またはグローバルも使いたい時）
    if not guild_objects:
        global_synced = await tree.sync()
        print(f"[global] synced: {[getattr(c, 'name', repr(c)) for c in global_synced]}")

    # 参考: 何が登録されているか必ずログ
    guild_cmds = []
    try:
        # 任意のギルドで確認（開発ギルドがあるならそれで）
        if guild_objects:
            guild_cmds = await tree.fetch_commands(guild=guild_objects[0])
            print(f"[fetch guild {guild_objects[0].id}] {len(guild_cmds)} cmds: {[getattr(c, 'name', repr(c)) for c in guild_cmds]}")
        global_cmds = await tree.fetch_commands()
        print(f"[fetch global] {len(global_cmds)} cmds: {[getattr(c, 'name', repr(c)) for c in global_cmds]}")
    except Exception as e:
        print("fetch_commands failed:", e)


def playPop(message: discord.message,channel: discord.VoiceClient):
    guildid = str(channel.guild.id)
    queue = voiceSource.get(guildid)
    if not queue:
        return
    source = queue.pop(0)
    channel.play(source,after=lambda e:playPop(message,channel))
    return

#when someone left voice channel
@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    #if nobody in voice channel, disconnect
    if before.channel is not None and len(before.channel.members) == 1:
        await before.channel.guild.voice_client.disconnect()
        return

@client.event
async def on_message(message: discord.Message):
    print(message.clean_content)
    if message.author.bot:
        return

    if message.guild is None:
        return

    voice_client = message.guild.voice_client
    if voice_client is None:
        return

    guildid = str(message.guild.id)

    guild_setting = userSetting.get(guildid)
    if guild_setting is None or str(message.author.id) not in guild_setting:
        return

    if message.channel.id not in botSetting.get("channelIDs", []):
        return

    if message.author.voice is None:
        return
    
    speakerid = int(guild_setting[str(message.author.id)]["voiceid"])
    

    content = message.clean_content

    content = re.sub(URL_PATTERN," URL ", content)

    content = re.sub(r"```.*?```"," コード ",content)
    content = re.sub(r"\n","、",content)


    if re.match(r"\d+d\d+",content):
        firstNum = int(content.split("d")[0])
        secondNum = int(content.split("d")[1])

        dice_rolls = [random.randint(1,secondNum) for _ in range(firstNum)]
        content = f"{firstNum}d{secondNum} : {sum(dice_rolls)}"
        await message.reply(content)

    if guildid in wordDictionary:
        for word in wordDictionary[guildid].keys():
            content = re.sub(patternDictionary[guildid][word],wordDictionary[guildid][word],content)

    if len(content) > 50:
        content = content[:50]

    if not core.is_model_loaded(speaker_id=speakerid):
        core.load_model(speaker_id=speakerid)

    wav = core.tts(text=content,speaker_id=speakerid)
    hoge = FFmpegPCMAudio(wav,pipe = True,stderr= sys.stderr)
    
    queue = voiceSource.setdefault(guildid, [])
    queue.append(hoge)
    if voice_client.is_playing():
        return
    playPop(message, voice_client)

client.run(botSetting["token"])
