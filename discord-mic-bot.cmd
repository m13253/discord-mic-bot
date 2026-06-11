@echo off

uv run --managed-python --env-file .env discord-mic-bot %* || pause
