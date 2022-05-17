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

import array
import asyncio
import asyncio.queues
import concurrent.futures
import ctypes
import logging
import time
import traceback
import typing
import os

import discord  # type: ignore
import discord.gateway  # type: ignore
import sounddevice  # type: ignore
from . import lumeter
if typing.TYPE_CHECKING:
    from . import view


class SoundDevice:
    __slots__ = ['name', 'is_default']

    def __init__(self, name: str, is_default: bool) -> None:
        self.name = name
        self.is_default = is_default

    def __repr__(self) -> str:
        if self.is_default:
            return '* {}'.format(self.name)
        return '  {}'.format(self.name)


class Model:
    __slots__ = ['v', 'loop', 'running', 'logger', 'discord_bot_token', 'discord_client', 'login_status', 'current_viewing_guild', 'input_stream', 'audio_warning_count', 'audio_queue', 'muted', 'opus_encoder', 'opus_encoder_private', 'opus_encoder_executor', 'lu_meter']
    muted_frame = array.array('f', [0.0] * (48000 * 20 // 1000 * 2))

    def __init__(self, discord_bot_token: str, loop: asyncio.AbstractEventLoop) -> None:
        self.v: typing.Optional['view.View'] = None
        self.loop = loop
        self.running = True

        self.logger = logging.getLogger('model')
        self.logger.setLevel(logging.INFO)
        logging_handler = logging.StreamHandler()
        logging_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'))
        self.logger.addHandler(logging_handler)

        self.discord_bot_token = discord_bot_token
        self.discord_client = discord.Client(loop=self.loop, max_messages=None, assume_unsync_clock=True, proxy=os.getenv('https_proxy'))
        self.login_status = 'Starting up…'
        self.current_viewing_guild: typing.Optional[discord.Guild] = None

        self.input_stream: typing.Optional[sounddevice.RawInputStream] = None
        self.audio_warning_count = 0
        # 2048 / 960 == 3, should work even with bad-designed audio systems (e.g. Windows MME)
        self.audio_queue: asyncio.Queue[typing.Optional['array.array[float]']] = asyncio.Queue(3)
        self.muted = False

        self.opus_encoder = discord.opus.Encoder()
        # Use the private function just to satisfy my paranoid of 1 Kbps == 1000 bps.
        # getattr is used to bypass the linter
        self.opus_encoder_private = getattr(discord.opus, '_lib')
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), discord.opus.CTL_SET_BITRATE, 128000)
        # FEC only works for voice, not music, and from my experience it hurts music quality severely.
        self.opus_encoder.set_fec(True)
        self.opus_encoder.set_expected_packet_loss_percent(0.15)
        self.opus_encoder_executor = concurrent.futures.ThreadPoolExecutor(1)

        self.lu_meter = lumeter.LUMeter(self.loop)

        self._set_up_events()

    def _set_up_events(self) -> None:
        async def on_connect() -> None:
            self.login_status = 'Retreving user info…'
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)

        self.discord_client.event(on_connect)

        async def on_disconnect() -> None:
            if self.running:
                self.login_status = 'Reconnecting…'
            else:
                self.login_status = 'Disconnected from Discord.'
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)

        self.discord_client.event(on_disconnect)

        async def on_ready() -> None:
            user = self.discord_client.user
            username = typing.cast(str, user.name) if user is not None else ''
            self.login_status = 'Logged in as: {}'.format(username)
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)
                self.v.loop.call_soon_threadsafe(self.v.guilds_updated)

        self.discord_client.event(on_ready)

        async def on_resumed() -> None:
            user = self.discord_client.user
            username = typing.cast(str, user.name) if user is not None else ''
            self.login_status = 'Logged in as: {}'.format(username)
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)
                self.v.loop.call_soon_threadsafe(self.v.guilds_updated)

        self.discord_client.event(on_resumed)

        async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
            if not isinstance(channel, discord.VoiceChannel):
                return
            if self.v is not None:
                if self.current_viewing_guild == channel.guild:
                    self.v.loop.call_soon_threadsafe(self.v.channels_updated)

        self.discord_client.event(on_guild_channel_create)

        async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
            if not isinstance(channel, discord.VoiceChannel):
                return
            if self.v is not None:
                if self.current_viewing_guild == channel.guild:
                    self.v.loop.call_soon_threadsafe(self.v.channels_updated)
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_guild_channel_delete)

        async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
            if not isinstance(after, discord.VoiceChannel):
                return
            if self.v is not None:
                if self.current_viewing_guild == after.guild:
                    self.v.loop.call_soon_threadsafe(self.v.channels_updated)
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_guild_channel_update)

        async def on_guild_join(guild: discord.Guild) -> None:
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.guilds_updated)
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_guild_join)

        async def on_guild_remove(guild: discord.Guild) -> None:
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.guilds_updated)
                if self.current_viewing_guild == guild:
                    self.v.loop.call_soon_threadsafe(self.v.channels_updated)
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_guild_remove)

        async def on_guild_update(before: discord.Guild, after: discord.Guild) -> None:
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.guilds_updated)
                if self.current_viewing_guild == after:
                    self.v.loop.call_soon_threadsafe(self.v.channels_updated)
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_guild_update)

        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.joined_updated)

        self.discord_client.event(on_voice_state_update)

    def attach_view(self, v: 'view.View') -> None:
        self.v = v
        self.v.loop.call_soon_threadsafe(self.v.login_status_updated)
        self.v.loop.call_soon_threadsafe(self.v.guilds_updated)
        self.v.loop.call_soon_threadsafe(self.v.device_updated)

    def get_login_status(self) -> str:
        return self.login_status

    def list_guilds(self) -> typing.List[discord.Guild]:
        return self.discord_client.guilds

    def list_channels(self) -> typing.List[discord.VoiceChannel]:
        if self.current_viewing_guild is None:
            return []
        return self.current_viewing_guild.voice_channels

    def list_joined(self) -> typing.List[discord.VoiceChannel]:
        return [i.channel for i in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients) if isinstance(i.channel, discord.VoiceChannel)]

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

    def view_guild(self, guild: typing.Optional[discord.Guild]) -> None:
        self.current_viewing_guild = guild
        if self.v is not None:
            self.v.loop.call_soon_threadsafe(self.v.channels_updated)
            self.v.loop.call_soon_threadsafe(self.v.joined_updated)

    async def join_voice(self, channel: discord.VoiceChannel) -> None:
        try:
            await channel.connect()
        except Exception:
            traceback.print_exc()
            return

        await self.loop.run_in_executor(self.opus_encoder_executor, self._reset_opus_encoder)

        if self.v is not None:
            self.v.loop.call_soon_threadsafe(self.v.joined_updated)

    def _reset_opus_encoder(self) -> None:
        CTL_RESET_STATE = 4028
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), CTL_RESET_STATE)

    async def leave_voice(self, channel: discord.VoiceChannel) -> None:
        futures = {voice_client.disconnect() for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients) if voice_client.channel == channel}
        if futures:
            try:
                await asyncio.wait(futures)
            except Exception:
                traceback.print_exc()

        if self.v is not None:
            self.v.loop.call_soon_threadsafe(self.v.joined_updated)

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

        self.input_stream = sounddevice.RawInputStream(samplerate=48000, blocksize=48000 * 20 // 1000, device=device_id, channels=2, dtype='float32', latency='low', callback=self._recording_callback, clip_off=True, dither_off=True, never_drop_input=False)
        try:
            self.input_stream.start()
        except Exception:
            traceback.print_exc()
            self.input_stream.close()
            self.input_stream = None

    async def set_bitrate(self, kbps: int) -> None:
        await self.loop.run_in_executor(self.opus_encoder_executor, self._set_bitrate, kbps)

    def _set_bitrate(self, kbps: int) -> None:
        kbps = min(512, max(12, kbps))
        self.opus_encoder_private.opus_encoder_ctl(getattr(self.opus_encoder, '_state'), discord.opus.CTL_SET_BITRATE, kbps * 1000)

    async def set_fec_enabled(self, enabled: bool) -> None:
        await self.loop.run_in_executor(self.opus_encoder_executor, self._set_fec_enabled, enabled)

    def _set_fec_enabled(self, enabled: bool) -> None:
        if enabled:
            self.opus_encoder.set_fec(True)
            self.opus_encoder.set_expected_packet_loss_percent(0.15)
        else:
            self.opus_encoder.set_fec(False)
            self.opus_encoder.set_expected_packet_loss_percent(0)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def _recording_callback(self, indata: typing.Any, frames: int, time: typing.Any, status: sounddevice.CallbackFlags) -> None:
        if status.input_underflow:
            self.audio_warning_count += 1
            self.logger.warn('Audio underflow: operating system unable to supply enough audio. (count={})'.format(self.audio_warning_count))
        if status.input_overflow:
            self.audio_warning_count += 1
            self.logger.warn('Audio overflow: recording thread not fast enough. (count={})'.format(self.audio_warning_count))
        if frames != 48000 * 20 // 1000:
            self.audio_warning_count += 1
            self.logger.warn('Audio frame size mismatch: {} != {}.'.format(frames, 48000 * 20 // 1000), self.audio_warning_count)

        if self.running:
            buffer = array.array('f')
            buffer.frombytes(bytes(indata)[:frames * 8])
            asyncio.run_coroutine_threadsafe(self._recording_callback_main_thread(buffer), self.loop).result()

    async def _recording_callback_main_thread(self, buffer: 'array.array[float]') -> None:
        try:
            self.audio_queue.put_nowait(buffer)
        except asyncio.queues.QueueFull:
            if not self.running:
                return
            self.audio_warning_count += 1
            self.logger.warn('Audio overflow: encoder not fast enough. (count={})'.format(self.audio_warning_count))

    async def _encode_voice_loop(self) -> None:
        consecutive_silence = 0
        timestamp_frames = 0

        try:
            while self.running:
                buffer = await self.audio_queue.get()
                if buffer is None:
                    return
                frame_size = len(buffer) // 2

                try:
                    timestamp_ns = time.monotonic_ns()
                except AttributeError:
                    timestamp_ns = int(time.monotonic() * 1000000000)

                if self.muted:
                    buffer = self.muted_frame
                    consecutive_silence += 1
                # For unknown reason, VoiceMeeter on Windows generates constant
                # noise in range [-1/32768, +1/32768] even I set the soundcard
                # to 48kHz 24-bit mode.
                # Okay, I know 24-bit is too good for human's ear, but it is
                # your fault to reduce the quality to 15-bit.
                elif max(buffer) * 65536 < 3 and min(buffer) * 65536 > -3:
                    consecutive_silence += 1
                else:
                    consecutive_silence = 0

                lu_meter_future = self.lu_meter.push(buffer)

                if consecutive_silence <= 1:
                    for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients):
                        if voice_client.is_connected():
                            voice_client_name: str = typing.cast(discord.VoiceChannel, voice_client.channel).name
                            if getattr(voice_client, '_dmb_speaking', discord.SpeakingState.none) != discord.SpeakingState.voice:
                                self.logger.info('Start speaking on: {}'.format(voice_client_name))
                                self._set_speaking_state(voice_client, discord.SpeakingState.voice, timestamp_ns)
                            elif timestamp_ns - getattr(voice_client, '_dmb_last_spoke', timestamp_ns) >= 60000000000:
                                self.logger.info('Continue speaking on: {}'.format(voice_client_name))
                                self._set_speaking_state(voice_client, discord.SpeakingState.voice, timestamp_ns)
                else:
                    for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients):
                        if voice_client.is_connected():
                            voice_client_name: str = typing.cast(discord.VoiceChannel, voice_client.channel).name
                            if getattr(voice_client, '_dmb_speaking', discord.SpeakingState.none) != discord.SpeakingState.none:
                                self.logger.info('Stop speaking on: {}'.format(voice_client_name))
                                self._set_speaking_state(voice_client, discord.SpeakingState.none, timestamp_ns)

                # When there's a break in the sent data, the packet transmission shouldn't simply stop. Instead, send five frames of silence (0xF8, 0xFF, 0xFE) before stopping to avoid unintended Opus interpolation with subsequent transmissions.
                # -- Discord SDK
                if consecutive_silence <= 5:
                    opus_packet = await self.loop.run_in_executor(self.opus_encoder_executor, self._encode_voice, buffer)
                    for voice_client in typing.cast(typing.List[discord.VoiceClient], self.discord_client.voice_clients):
                        if voice_client.is_connected():
                            send_func = self._send_audio_packet(voice_client, opus_packet, timestamp_frames)
                            self.loop.call_soon(send_func)
                            # self.loop.call_later(0.01, send_func)

                timestamp_frames = (timestamp_frames + frame_size) & 0xffffffff
                await lu_meter_future

        except Exception:
            traceback.print_exc()
        finally:
            if self.v is not None:
                self.v.stop()

    # A rewrite of discord.VoiceClient.send_audio_packet.
    # The timestamp is supplied from outside so all silent frames get counted.
    def _send_audio_packet(self, voice_client: discord.VoiceClient, opus_packet: bytes, timestamp_frames: int) -> typing.Callable[[], None]:
        sock = voice_client.socket
        endpoint_ip = voice_client.endpoint_ip
        endpoint_port: int = voice_client.voice_port  # type: ignore
        sequence = voice_client.sequence

        voice_client.timestamp = timestamp_frames
        udp_packet = getattr(voice_client, '_get_voice_packet')(opus_packet)
        voice_client.sequence = (voice_client.sequence + 1) & 0xffff

        def send() -> None:
            if sock is None:
                return
            try:
                sock.sendto(udp_packet, (endpoint_ip, endpoint_port))
            except BlockingIOError:
                self.logger.warning('Network too slow, a packet is dropped. (seq={}, ts={})'.format(sequence, timestamp_frames))

        return send

    def _set_speaking_state(self, voice_client: discord.VoiceClient, state: int, timestamp_ns: int) -> None:
        setattr(voice_client, '_dmb_speaking', state)
        setattr(voice_client, '_dmb_last_spoke', timestamp_ns)
        asyncio.ensure_future(voice_client.ws.speak(state), loop=self.loop)

    def _encode_voice(self, buffer: 'array.array[float]') -> bytes:
        c_buffer = ctypes.cast(buffer.buffer_info()[0], ctypes.POINTER(ctypes.c_float))
        max_data_bytes = len(buffer) * 4
        output = (ctypes.c_char * max_data_bytes)()
        output_len = self.opus_encoder_private.opus_encode_float(getattr(self.opus_encoder, '_state'), c_buffer, len(buffer) // 2, output, max_data_bytes)
        return bytes(output[:output_len])

    async def run(self) -> None:
        try:
            asyncio.ensure_future(self._encode_voice_loop(), loop=self.loop)

            self.login_status = 'Logging in…'
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)
            await self.discord_client.login(self.discord_bot_token, bot=True)

            self.login_status = 'Connecting to Discord server…'
            self.logger.info(self.login_status)
            if self.v is not None:
                self.v.loop.call_soon_threadsafe(self.v.login_status_updated)

            await self.discord_client.connect()
        finally:
            if self.v is not None:
                self.v.stop()

    def stop(self) -> None:
        self.running = False
        self.logger.info('Gracefully stopping, may take some time…')
        if self.input_stream is not None:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None
        asyncio.ensure_future(self._stop(), loop=self.loop)

    async def _stop(self) -> None:
        await self.discord_client.close()
        self.audio_queue.put_nowait(None)
        self.opus_encoder_executor.shutdown()
