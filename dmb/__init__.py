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

import asyncio
import concurrent.futures
import os
import threading
import typing

if typing.TYPE_CHECKING:
    from . import model


class ModelThread(threading.Thread):
    def __init__(self, discord_bot_token: str) -> None:
        super().__init__()
        self.discord_bot_token = discord_bot_token
        self.init_finished: concurrent.futures.Future['model.Model'] = concurrent.futures.Future()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(loop))
        except BaseException as exc:
            if not self.init_finished.done():
                self.init_finished.set_exception(exc)
            raise
        finally:
            loop.close()

    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        from . import model

        m = model.Model(self.discord_bot_token, loop)
        self.init_finished.set_result(m)
        await m.run()


class UIThread:
    def __init__(self, m: 'model.Model') -> None:
        self.m = m

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(loop))
        finally:
            loop.close()

    async def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        from . import view

        v = view.View(self.m, loop)
        await v.run()


def main() -> None:
    discord_bot_token = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
    if not discord_bot_token:
        print('Unable to find a Discord bot token.')
        print('Please set the DISCORD_BOT_TOKEN environment variable.')
        return

    model_thread = ModelThread(discord_bot_token)
    model_thread.start()
    m = model_thread.init_finished.result()

    try:
        ui_thread = UIThread(m)
        ui_thread.run()
    finally:
        m.stop()
        model_thread.join()
