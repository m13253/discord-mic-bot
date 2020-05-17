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
import discord  # type: ignore
import tkinter
import tkinter.messagebox
import tkinter.ttk
import typing
if typing.TYPE_CHECKING:
    from . import model


class View:
    def __init__(self, m: model.Model) -> None:
        self.m = m
        self.running = True

        self.root = tkinter.Tk()
        self.root.bind('<Destroy>', self.on_destroy)

        self.login_status = tkinter.StringVar(self.root, 'Starting up…')
        self.guilds: typing.List[discord.Guild] = []
        self.channels: typing.List[discord.VoiceChannel] = []
        self.joined: typing.List[discord.VoiceChannel] = []
        self.hostapi = tkinter.StringVar(self.root, '')
        self.device = tkinter.StringVar(self.root, '')
        self.bitrate = tkinter.StringVar(self.root, 128)
        self.muted = tkinter.BooleanVar(self.root, False)

        self.root.title('Discord Mic Bot')
        self.frame = tkinter.ttk.Frame(self.root)
        self.frame.grid(column=0, row=0, sticky=tkinter.NSEW)

        tkinter.ttk.Label(self.frame, textvariable=self.login_status).grid(column=0, row=0, columnspan=3, padx=16, pady=(16, 4), sticky=tkinter.NSEW)

        top_row = tkinter.ttk.Frame(self.frame)
        top_row.grid(column=0, row=1, columnspan=4, sticky=tkinter.W)
        tkinter.ttk.Label(top_row, text='Device:').grid(column=0, row=0, padx=(16, 0), pady=(4, 4), sticky=tkinter.NSEW)
        self.hostapi_combobox = tkinter.ttk.Combobox(top_row, textvariable=self.hostapi, width=12, state='readonly')
        self.hostapi_combobox.grid(column=1, row=0, pady=(4, 4), sticky=tkinter.NSEW)
        self.hostapi_combobox.bind('<<ComboboxSelected>>', self.on_device_changed)
        self.device_combobox = tkinter.ttk.Combobox(top_row, textvariable=self.device, width=16, state='readonly')
        self.device_combobox.grid(column=2, row=0, padx=(0, 8), pady=(4, 4), sticky=tkinter.NSEW)
        self.device_combobox.bind('<<ComboboxSelected>>', self.on_device_changed)
        tkinter.ttk.Label(top_row, text='Bitrate:').grid(column=3, row=0, padx=(8, 0), pady=(4, 4), sticky=tkinter.NSEW)
        bitrate_combobox = tkinter.ttk.Combobox(top_row, textvariable=self.bitrate, values=(16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512), width=6)
        bitrate_combobox.grid(column=4, row=0, pady=(4, 4), sticky=tkinter.NSEW)
        bitrate_combobox.bind('<<ComboboxSelected>>', self.on_bitrate_changed)
        bitrate_combobox.bind('<FocusOut>', self.on_bitrate_changed)
        bitrate_combobox.bind('<Return>', self.on_bitrate_changed)
        tkinter.ttk.Label(top_row, text='Kbps').grid(column=5, row=0, padx=(0, 8), pady=(4, 4), sticky=tkinter.NSEW)
        tkinter.ttk.Checkbutton(top_row, text='Mute', variable=self.muted, command=self.on_mute_changed).grid(column=6, row=0, padx=(8, 8), pady=(4, 4), sticky=tkinter.NSEW)

        tkinter.ttk.Label(self.frame, text='Guilds:').grid(column=0, row=2, padx=(16, 8), pady=(4, 0), sticky=tkinter.NSEW)
        tkinter.ttk.Label(self.frame, text='Channels:').grid(column=1, row=2, padx=(8, 0), pady=(4, 0), sticky=tkinter.NSEW)
        tkinter.ttk.Label(self.frame, text='Joined:').grid(column=3, row=2, padx=(0, 16), pady=(4, 0), sticky=tkinter.NSEW)

        guilds_list_panel = tkinter.ttk.Frame(self.frame)
        guilds_list_panel.grid(column=0, row=3, padx=(16, 8), pady=(0, 16), sticky=tkinter.NSEW)
        self.guilds_list = tkinter.Listbox(guilds_list_panel, height=16)
        self.guilds_list.grid(column=0, row=0, sticky=tkinter.NSEW)
        self.guilds_list.bind('<<ListboxSelect>>', self.on_guild_changed)
        guilds_list_scroll = tkinter.ttk.Scrollbar(guilds_list_panel, orient=tkinter.VERTICAL, command=self.guilds_list.yview)
        guilds_list_scroll.grid(column=1, row=0, sticky=tkinter.NSEW)
        self.guilds_list['yscrollcommand'] = guilds_list_scroll.set
        guilds_list_panel.grid_rowconfigure(0, weight=1)
        guilds_list_panel.grid_columnconfigure(0, weight=1)

        channels_list_panel = tkinter.ttk.Frame(self.frame)
        channels_list_panel.grid(column=1, row=3, padx=(8, 0), pady=(0, 16), sticky=tkinter.NSEW)
        self.channels_list = tkinter.Listbox(channels_list_panel, height=16)
        self.channels_list.grid(column=0, row=0, sticky=tkinter.NSEW)
        channels_list_scroll = tkinter.ttk.Scrollbar(channels_list_panel, orient=tkinter.VERTICAL, command=self.channels_list.yview)
        channels_list_scroll.grid(column=1, row=0, sticky=tkinter.NSEW)
        self.channels_list['yscrollcommand'] = channels_list_scroll.set
        channels_list_panel.grid_rowconfigure(0, weight=1)
        channels_list_panel.grid_columnconfigure(0, weight=1)

        joined_list_panel = tkinter.ttk.Frame(self.frame)
        joined_list_panel.grid(column=3, row=3, padx=(0, 16), pady=(0, 16), sticky=tkinter.NSEW)
        self.joined_list = tkinter.Listbox(joined_list_panel, height=16)
        self.joined_list.grid(column=0, row=0, sticky=tkinter.NSEW)
        joined_list_scroll = tkinter.ttk.Scrollbar(joined_list_panel, orient=tkinter.VERTICAL, command=self.joined_list.yview)
        joined_list_scroll.grid(column=1, row=0, sticky=tkinter.NSEW)
        self.joined_list['yscrollcommand'] = joined_list_scroll.set
        joined_list_panel.grid_rowconfigure(0, weight=1)
        joined_list_panel.grid_columnconfigure(0, weight=1)

        add_remove_buttons = tkinter.ttk.Frame(self.frame)
        add_remove_buttons.grid(column=2, row=3, pady=(0, 16))
        tkinter.ttk.Button(add_remove_buttons, text='→', width=2, command=self.on_add_button_pressed).grid(column=0, row=0, pady=4, sticky=tkinter.S)
        tkinter.ttk.Button(add_remove_buttons, text='←', width=2, command=self.on_remove_button_pressed).grid(column=0, row=1, pady=4, sticky=tkinter.N)

        self.frame.grid_rowconfigure(3, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_columnconfigure(3, weight=1)

        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.root.update()
        self.root.minsize(self.root.winfo_width(), self.root.winfo_height())

        m.attach_view(self)

    def login_status_updated(self) -> None:
        self.login_status.set(self.m.get_login_status())

    def guilds_updated(self) -> None:
        self.guilds = self.m.list_guilds()
        self.guilds_list.delete(0, tkinter.END)
        for i in self.guilds:
            self.guilds_list.insert(tkinter.END, typing.cast(str, i.name))

    def channels_updated(self) -> None:
        self.channels = self.m.list_channels()
        self.channels_list.delete(0, tkinter.END)
        for i in self.channels:
            self.channels_list.insert(tkinter.END, typing.cast(str, i.name))

    def joined_updated(self) -> None:
        self.joined = self.m.list_joined()
        self.joined_list.delete(0, tkinter.END)
        for i in self.joined:
            self.joined_list.insert(tkinter.END, typing.cast(str, i.name))

    def device_updated(self) -> None:
        hostapis = self.m.list_sound_hostapis()
        self.hostapi_combobox['values'] = tuple(hostapis)
        current_hostapi: str = self.hostapi.get()
        if current_hostapi not in hostapis:
            if len(hostapis) != 0:
                current_hostapi = hostapis[0]
            else:
                current_hostapi = ''
            self.hostapi.set(current_hostapi)

        sound_input_devices = self.m.list_sound_input_devices(current_hostapi)
        self.device_combobox['values'] = tuple((i.name for i in sound_input_devices))
        current_device: str = self.device.get()
        if current_device not in (i.name for i in sound_input_devices):
            current_device = ''
            for i in sound_input_devices:
                if i.is_default:
                    current_device = i.name
            self.device.set(current_device)
            self.m.start_recording(current_hostapi, current_device)

    def on_destroy(self, event: tkinter.Event) -> None:
        self.running = False

    def on_guild_changed(self, event: tkinter.Event) -> None:
        current_selections: typing.Tuple[int] = self.guilds_list.curselection()
        current_guild: typing.Optional[discord.Guild] = None
        if len(current_selections) != 0 and current_selections[0] < len(self.guilds):
            current_guild = self.guilds[current_selections[0]]
        self.channels_list.delete(0, tkinter.END)
        asyncio.ensure_future(self.m.view_guild(current_guild))

    def on_add_button_pressed(self) -> None:
        current_selections: typing.Tuple[int] = self.channels_list.curselection()
        if len(current_selections) == 0 or current_selections[0] >= len(self.channels):
            return
        current_channel = self.channels[current_selections[0]]
        asyncio.ensure_future(self.m.join_voice(current_channel))

    def on_remove_button_pressed(self) -> None:
        current_selections: typing.Tuple[int] = self.joined_list.curselection()
        if len(current_selections) == 0 and current_selections[0] >= len(self.joined):
            return
        current_channel = self.joined[current_selections[0]]
        asyncio.ensure_future(self.m.leave_voice(current_channel))

    def on_device_changed(self, event: tkinter.Event) -> None:
        hostapis = self.m.list_sound_hostapis()
        self.hostapi_combobox['values'] = tuple(hostapis)
        current_hostapi: str = self.hostapi.get()
        if current_hostapi not in hostapis:
            if len(hostapis) != 0:
                current_hostapi = hostapis[0]
            else:
                current_hostapi = ''
            self.hostapi.set(current_hostapi)

        sound_input_devices = self.m.list_sound_input_devices(current_hostapi)
        self.device_combobox['values'] = tuple((i.name for i in sound_input_devices))
        current_device: str = self.device.get()
        if current_device not in (i.name for i in sound_input_devices):
            current_device = ''
            for i in sound_input_devices:
                if i.is_default:
                    current_device = i.name
            self.device.set(current_device)
        self.m.start_recording(current_hostapi, current_device)

    def on_bitrate_changed(self, event: tkinter.Event) -> None:
        bitrate_str: str = self.bitrate.get()
        try:
            bitrate = min(512, max(12, int(bitrate_str)))
        except ValueError:
            bitrate = 128
        self.m.set_bitrate(bitrate)
        self.bitrate.set(bitrate)

    def on_mute_changed(self) -> None:
        muted: bool = self.muted.get()
        self.m.set_muted(muted)

    async def run_loop(self) -> None:
        try:
            while self.running:
                self.root.update()
                await asyncio.sleep(1 / 30)
        finally:
            await self.m.stop()
