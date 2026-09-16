"""FFmpeg source construction; input seeking actually changes decoded audio."""
import discord


class FFmpegSourceFactory:
    def __init__(self, executable):
        self.executable = executable

    def __call__(self, url, volume, *, position=0):
        if type(position) is not int or position < 0:
            raise ValueError("Invalid audio position")
        before = "-nostdin -protocol_whitelist https,tls,tcp,crypto -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000"
        if position:
            before += f" -ss {position}"
        pcm = discord.FFmpegPCMAudio(url, executable=self.executable,
            # Do not pass subprocess.DEVNULL here. discord.py 2.7 treats any
            # non-file stderr value as a pipe and its reader calls .write() on
            # that value, which is an int for DEVNULL.
            before_options=before, options="-vn -loglevel fatal")
        return discord.PCMVolumeTransformer(pcm, volume=volume / 100)
