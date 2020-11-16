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

#from __future__ import annotations
import asyncio
import array
import concurrent.futures
import typing
import threading
import numpy  # type: ignore
import scipy.signal  # type: ignore


class LUMeter:
    __slots__ = ['loop', 'buffer', 'zl', 'zr', 'lock', 'executor']
    # ITU-R BS.1770 coefficients at 48kHz sample rate
    # If you are looking for a set of sample-rate-irrelevant version, check out https://github.com/BrechtDeMan/loudness.py
    coeff_b = numpy.array([1.53512485958697, -5.76194590858032, 8.11691004925258, -5.08848181111208, 1.19839281085285])
    coeff_a = numpy.array([1, -3.68070674801639, 5.08704524797113, -3.13154635144673, 0.72520888847787])

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.buffer = numpy.zeros((2, 19200), dtype=numpy.float32)
        self.zl = scipy.signal.lfilter_zi(self.coeff_b, self.coeff_a)
        self.zr = self.zl
        self.lock = threading.Lock()
        self.executor = concurrent.futures.ThreadPoolExecutor(1)

    async def push(self, buffer: array.array) -> None:
        if len(buffer) == 0:
            return
        if len(buffer) > 38400:
            buffer = buffer[-38400:]
        await self.loop.run_in_executor(self.executor, self._push, buffer)

    def _push(self, buffer: array.array) -> None:
        frame_size = len(buffer) // 2
        x = numpy.array(buffer).reshape((2, -1), order='F')
        numpy.nan_to_num(x, copy=False)
        if not numpy.all(numpy.isfinite(self.zl)):
            self.zl = scipy.signal.lfilter_zi(self.coeff_b, self.coeff_a)
        if not numpy.all(numpy.isfinite(self.zr)):
            self.zr = scipy.signal.lfilter_zi(self.coeff_b, self.coeff_a)
        yl, self.zl = scipy.signal.lfilter(self.coeff_b, self.coeff_a, x[0], zi=self.zl)
        yr, self.zr = scipy.signal.lfilter(self.coeff_b, self.coeff_a, x[1], zi=self.zr)
        with self.lock:
            self.buffer[:, :-frame_size] = self.buffer[:, frame_size:]
            numpy.square(yl, out=self.buffer[0, -frame_size:])
            numpy.square(yr, out=self.buffer[1, -frame_size:])
            numpy.nan_to_num(self.buffer[-frame_size:], copy=False)

    def momentary_lufs(self) -> typing.Tuple[float, float]:
        with self.lock:
            mean = numpy.mean(self.buffer, axis=1, dtype=numpy.float64)
        with numpy.errstate(divide='ignore'):
            lufs = numpy.log10(mean) * 10.0 - 0.691
        return lufs[0], lufs[1]
