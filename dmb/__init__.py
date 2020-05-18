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
from . import model
from . import view


async def main() -> None:
    try:
        with open('token.txt', 'r') as token_file:
            discord_bot_token = token_file.read().strip()
        if not discord_bot_token:
            raise ValueError
    except (FileNotFoundError, ValueError):
        print('Unable to find a Discord bot token.')
        print('Please put your Discord bot token in token.txt.')
        return

    m = model.Model(discord_bot_token)
    v = view.View(m)

    f1 = v.run_loop()
    f2 = m.run()
    await asyncio.wait((f1, f2))
