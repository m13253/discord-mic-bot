# discord-mic-bot -- Discord bot to connect to your microphone
# Copyright (C) 2020  Star Brilliant
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations
import asyncio
import asyncio.queues
import ctypes
import typing
import discord  # type: ignore
import discord.gateway  # type: ignore
import sounddevice  # type: ignore
import traceback
if typing.TYPE_CHECKING:
    from . import view


class SoundDevice:
    def __init__(self, name: str, is_default: bool) -> None:
        self.name = name
        self.is_default = is_default

    def __repr__(self) -> str:
        if self.is_default:
            return '* {}'.format(self.name)
        return '  {}'.format(self.name)


class Model:
    def __init__(self, discord_bot_token: str) -> None:
        self.v: typing.Optional[view.View] = None
        self.running = True

        self.loop = asyncio.get_running_loop()

        self.discord_bot_token = discord_bot_token
        self.discord_client: discord.Client = discord.Client(max_messages=None, assume_unsync_clock=True)
        self.login_status = 'Starting up…'
        self.current_viewing_guild: typing.Optional[discord.Guild] = None
        self.channels: typing.List[discord.VoiceChannel] = []

        self.input_stream: typing.Optional[sounddevice.RawInputStream] = None
        self.audio_queue = asyncio.Queue(3)  #  2048 / 960, should work even with bad-designed audio systems (e.g. Windows MME)
        self.muted = False
        self.warning_count_size = 0
        self.warning_count_overflow = 0

        self.opus_encoder = discord.opus.Encoder()
        # Use the private function just to satisfy my paranoid of 1 Kbps == 1000 bps.
        # getattr is used to bypass the linter
        self.opus_encoder_private = getattr(discord.opus, '_lib')
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), discord.opus.CTL_SET_BITRATE, 128000)
        # FEC only works for voice, not music, and from my experience it hurts music quality severely.
        self.opus_encoder.set_fec(False)
        self.opus_encoder.set_expected_packet_loss_percent(0)

        self._set_up_events()

    def _set_up_events(self) -> None:
        async def on_connect() -> None:
            self.login_status = 'Retreving user info…'
            if self.v is not None:
                self.v.login_status_updated()

        self.discord_client.event(on_connect)

        async def on_disconnect() -> None:
            self.login_status = 'Reconnecting…'
            if self.v is not None:
                self.v.login_status_updated()

        self.discord_client.event(on_disconnect)

        async def on_ready() -> None:
            user: typing.Optional[discord.ClientUser] = typing.cast(typing.Any, self.discord_client.user)
            username = typing.cast(str, user.name) if user is not None else ''
            self.login_status = 'Logged in as: {}'.format(username)
            if self.v is not None:
                self.v.login_status_updated()
                self.v.guilds_updated()

        self.discord_client.event(on_ready)

        async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
            if not isinstance(channel, discord.VoiceChannel):
                return
            if channel.guild == self.current_viewing_guild:
                self.view_guild(self.current_viewing_guild)

        self.discord_client.event(on_guild_channel_create)

        async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
            if not isinstance(channel, discord.VoiceChannel):
                return
            if channel in self.channels:
                self.channels.remove(channel)
                if self.v is not None:
                    self.v.channels_updated()
            if self.v is not None:
                self.v.joined_updated()

        self.discord_client.event(on_guild_channel_delete)

        async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
            if not isinstance(after, discord.VoiceChannel):
                return
            if before in self.channels:
                for i, c in enumerate(self.channels):
                    if c == before:
                        self.channels[i] = after
                if self.v is not None:
                    self.v.channels_updated()
            if self.v is not None:
                self.v.joined_updated()

        self.discord_client.event(on_guild_channel_update)

        async def on_guild_join(guild: discord.Guild) -> None:
            if self.v is not None:
                self.v.guilds_updated()

        self.discord_client.event(on_guild_join)

        async def on_guild_remove(guild: discord.Guild) -> None:
            if self.v is not None:
                self.v.guilds_updated()

        self.discord_client.event(on_guild_remove)

        async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
            if self.v is not None:
                self.v.guilds_updated()

        self.discord_client.event(on_guild_update)

        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
            if self.v is not None:
                self.v.joined_updated()

        self.discord_client.event(on_voice_state_update)

    def attach_view(self, v: view.View) -> None:
        self.v = v
        self.v.login_status_updated()
        self.v.guilds_updated()
        self.v.device_updated()

    def get_login_status(self) -> str:
        return self.login_status

    def list_guilds(self) -> typing.List[discord.Guild]:
        return self.discord_client.guilds

    def list_channels(self) -> typing.List[discord.VoiceChannel]:
        return self.channels

    def list_joined(self) -> typing.List[discord.VoiceChannel]:
        return [i.channel for i in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients) if i.is_connected() and isinstance(i.channel, discord.VoiceChannel)]

    def list_sound_hostapis(self) -> typing.List[str]:
        hostapis = typing.cast(typing.Tuple[typing.Dict[str, typing.Any], ...], sounddevice.query_hostapis())
        return [i['name'] for i in hostapis]

    def list_sound_input_devices(self, hostapi: str) -> typing.List[SoundDevice]:
        hostapis = typing.cast(typing.Tuple[typing.Dict[str, typing.Any], ...], sounddevice.query_hostapis())
        devices = typing.cast(sounddevice.DeviceList, sounddevice.query_devices())

        default_input_id, _ = typing.cast(typing.Tuple[typing.Optional[int], typing.Optional[int]], sounddevice.default.device)
        for api in hostapis:
            if api['name'] == hostapi:
                default_input_id = api['default_input_device']
                break
        else:
            return []

        return [SoundDevice(typing.cast(str, dev['name']), idx == default_input_id) for idx, dev in enumerate(typing.cast(typing.Iterable[typing.Dict[str, typing.Any]], devices)) if dev['max_input_channels'] > 0 and dev['hostapi'] < len(hostapis) and hostapis[typing.cast(int, dev['hostapi'])]['name'] == hostapi]

    async def view_guild(self, guild: typing.Optional[discord.Guild]) -> None:
        self.channels = []
        self.current_viewing_guild = guild
        if guild is None:
            return
        channels = await typing.cast(typing.Awaitable[typing.List[discord.abc.GuildChannel]], guild.fetch_channels())
        if self.current_viewing_guild != guild:
            return
        self.channels = [i for i in channels if isinstance(i, discord.VoiceChannel)]
        if self.v is not None:
            self.v.channels_updated()

    async def join_voice(self, channel: discord.VoiceChannel) -> None:
        try:
            await channel.connect()
        except Exception:
            traceback.print_last()
            return

        CTL_RESET_STATE = 4028
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), CTL_RESET_STATE)

        if self.v is not None:
            self.v.joined_updated()

    async def leave_voice(self, channel: discord.VoiceChannel) -> None:
        futures = {voice_client.disconnect() for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients) if voice_client.channel == channel}
        if futures:
            try:
                await asyncio.wait(futures)
            except Exception:
                traceback.print_last()

        if self.v is not None:
            self.v.joined_updated()

    def start_recording(self, hostapi: str, device: str) -> None:
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

        hostapis = typing.cast(typing.Tuple[typing.Dict[str, typing.Any], ...], sounddevice.query_hostapis())
        devices = typing.cast(sounddevice.DeviceList, sounddevice.query_devices())

        device_id: int
        for idx, dev in enumerate(typing.cast(typing.Iterable[typing.Dict[str, typing.Any]], devices)):
            if dev['name'] == device and dev['max_input_channels'] > 0 and dev['hostapi'] < len(hostapis) and hostapis[typing.cast(int, dev['hostapi'])]['name'] == hostapi:
                device_id = idx
                break
        else:
            return

        self.input_stream = sounddevice.RawInputStream(samplerate=48000, blocksize=48000 * 20 // 1000, device=device_id, channels=2, dtype='float32', latency='low', callback=self._recording_callback, clip_off=True, dither_off=False, never_drop_input=False)
        try:
            self.input_stream.start()
        except Exception:
            traceback.print_last()
            self.input_stream.close()
            self.input_stream = None

    def set_bitrate(self, kbps: int) -> None:
        kbps = min(512, max(12, kbps))
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), discord.opus.CTL_SET_BITRATE, kbps * 1000)

    def set_fec_enabled(self, enabled: bool) -> None:
        if enabled:
            self.opus_encoder.set_fec(True)
            self.opus_encoder.set_expected_packet_loss_percent(0.15)
        else:
            self.opus_encoder.set_fec(False)
            self.opus_encoder.set_expected_packet_loss_percent(0)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def _recording_callback(self, indata: typing.Any, frames: int, time: typing.Any, status: sounddevice.CallbackFlags) -> None:
        if frames != 48000 * 20 // 1000:
            self.warning_count_size += 1
            print('{}: Audio frame size mismatch: {} != {}'.format(self.warning_count_size, frames, 48000 * 20 // 1000))
        indata = bytes(indata)[:frames * 8]
        if self.running:
            self.loop.call_soon_threadsafe(self._recording_callback_main_thread, indata)

    def _recording_callback_main_thread(self, indata: bytes) -> None:
        try:
            self.audio_queue.put_nowait(indata)
        except asyncio.queues.QueueFull:
            if not self.running:
                return
            self.warning_count_overflow += 1
            print('{}: Audio overflow: encoder not fast enough.'.format(self.warning_count_overflow))

    async def _encode_voice_loop(self) -> None:
        consecutive_silence = 0
        while self.running:
            buffer: typing.Optional[bytes] = await self.audio_queue.get()
            if buffer is None:
                return

            if self.muted:
                buffer = bytes(len(buffer))
                consecutive_silence += 1
            elif buffer.count(0) == len(buffer):
                consecutive_silence += 1
            else:
                consecutive_silence = 0

            speaking = discord.SpeakingState.soundshare if consecutive_silence <= 1 else discord.SpeakingState.none
            for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients):
                if voice_client.is_connected() and getattr(voice_client, '_dmb_speaking', discord.SpeakingState.none) != speaking:
                    asyncio.ensure_future(typing.cast(discord.gateway.DiscordVoiceWebSocket, voice_client.ws).speak(speaking))
                    setattr(voice_client, '_dmb_speaking', speaking)

            # When there's a break in the sent data, the packet transmission shouldn't simply stop. Instead, send five frames of silence (0xF8, 0xFF, 0xFE) before stopping to avoid unintended Opus interpolation with subsequent transmissions.
            if consecutive_silence > 5:
                continue

            max_data_bytes = len(buffer)
            output = (ctypes.c_char * max_data_bytes)()
            output_len = self.opus_encoder_private.opus_encode_float(getattr(self.opus_encoder, '_state'), buffer, len(buffer) // 8, output, max_data_bytes)

            packet = bytes(output[:output_len])
            for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients):
                if voice_client.is_connected():
                    try:
                        voice_client.send_audio_packet(packet, encode=False)
                    except Exception:
                        traceback.print_last()

    async def run(self) -> None:
        asyncio.ensure_future(self._encode_voice_loop())

        self.login_status = 'Logging in…'
        if self.v is not None:
            self.v.login_status_updated()
        await self.discord_client.login(self.discord_bot_token, bot=True)

        self.login_status = 'Connecting to Discord server…'
        if self.v is not None:
            self.v.login_status_updated()
        asyncio.ensure_future(self.discord_client.connect())

        await self.discord_client.wait_until_ready()

    async def stop(self) -> None:
        self.running = False
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None
        await self.audio_queue.put(None)
        await self.discord_client.close()
