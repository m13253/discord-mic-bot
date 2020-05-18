# discord-mic-bot

Discord bot to connect to your microphone―and you can have stereo sound

## Description

Discord transmits only mono sound to voice channel, which makes it a bad
experience if you want to sing karaoke or play an instrument in a voice party.
However, bot can transmit stereo sound to voice channel. Thus, you can connect
to your party channel as a bot.

## Installation

First, you need to install Python 3.7 or later version and download
discord-mic-bot.

Then, in terminal or command prompt, type:
```sh
cd /path/to/discord-mic-bot
pip3 install -r requirements.txt
```

## Obtaining a bot token

You need to obtain a bot token to log into Discord's server.

1. Go to <https://discord.com/developers/applications> and click on "New
   Application".

2. Inside the settings panel of your new application, click on "Bot".

3. Create a new bot. When asked about permissions, simply leave blank is enough.

4. Click on "Copy Token".

5. Open the file named `token.txt` and paste your token inside that file.

## Usage

For Linux or macOS users, `discord-mic-bot` is the entry point.

For Windows users, `discord-mic-bot.cmd` is the entry point.

## License

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

You should have received a copy of the [GNU General Public License](LICENSE)
along with this program.

## Acknowledgment

This program is inspired by (but not a fork from)
[discord-audio-pipe](https://github.com/QiCuiHub/discord-audio-pipe).
Thank you QiCuiHub!