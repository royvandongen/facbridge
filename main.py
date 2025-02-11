import asyncio
import re
import time
import os
import logging
from os.path import dirname

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

import discord
from discord.ext import commands

from mcrcon import MCRcon

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)

class FacLogHandler(PatternMatchingEventHandler):
    # Watches a log file for useful events
    def __init__(self, fbot, logfile):
        self.fbot = fbot
        self.log_loc = logfile
        self.logfile = None

        super().__init__([logfile])
        self.spin_up()
        self.observer = Observer()
        self.observer.schedule(self, dirname(self.log_loc), recursive=False)
        self.observer.start()
        print("started")

    def spin_up(self):
        # When the bridge first starts up, wait for factorio to start and
        # create the log file, then read to the end so we don't duplicate
        # any messages

        self.logfile = None
        elapsed = 0
        while self.logfile is None:
            try:
                self.logfile = open(self.log_loc, 'r')
            except:
                time.sleep(1)
                elapsed + 1
                if elapsed > 20:
                    raise Exception("Timed out opening log file!")

        # read up to last line before EOF
        for line in self.logfile:
            pass

    def on_created(self, event):
        # Factorio moves the file aside and creates a new one.
        # Close the existing file and look for the new one.
        self.logfile.close()
        self.spin_up()

    def on_modified(self, event):
        # When a line is written to the log, handle any action needed.
        # Right now, there's only chat.
        for line in self.logfile:
            m = re.match(".*Factorio-Event-Logger+.*\[([A-Z\ ]+)\] (.+)$", line)

            if m is not None:
                
                dispatch = {
                    "JOIN": self.got_join,
                    "LEAVE": self.got_leave,
                    "CHAT": self.got_chat,
                    "DIED": self.got_died,
                    "EVOLUTION": self.got_evolution,
                    "RESEARCH STARTED": self.got_research_started,
                    "RESEARCH FINISHED": self.got_research_finished,
                    "RESEARCH CANCELLED": self.got_research_cancelled,
                    }

                method = dispatch.get(m.group(1), None)

                if method is not None:
                    print("Match found in Mod Logs")
                    method(m.group(2))
                #else:
                    #self.default_handler(m.group(1), m.group(2))

    def default_handler(self, kind, text):
        logger.debug("Factorio sent unknown '%s': '%s'", kind, text)
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_chat(self, text):
        logger.debug("Factorio sent CHAT '%s'", text)
        user, msg = text.split(": ", 1)
        if user == "<server>":
            return

        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(":incoming_envelope: " + text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_join(self, text):
        logger.debug("Factorio sent JOIN '%s'", text)
        user = text
        if user == "<server>":
            return

        text = ":arrow_up: " + user + " joined the game"
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_leave(self, text):
        logger.debug("Factorio sent LEAVE '%s'", text)
        user, reason = text.split(" ", 1)
        if user == "<server>":
            return

        text = ":arrow_down: " + user + " left the game with reason: " + reason
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_died(self, text):
        logger.debug("Factorio sent DIED '%s'", text)
        user, reason = text.split(" ", 1)
        if user == "<server>":
            return

        text = ":coffin: " + user + " died because of " + reason
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_evolution(self, text):
        logger.debug("Factorio sent EVOLUTION '%s'", text)
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(":dna: Current Evolution: " + text)
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_research_started(self, text):
        logger.debug("Factorio sent RESEARCH STARTED '%s'", text)
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(":test_tube: " + text + " research started")
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_research_finished(self, text):
        logger.debug("Factorio sent RESEARCH FINISHED '%s'", text)
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(":test_tube::tada: " + text + " research finished")
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

    def got_research_cancelled(self, text):
        logger.debug("Factorio sent RESEARCH CANCELLED '%s'", text)
        channel = self.fbot.get_channel(self.fbot.bridge_id)
        coro = channel.send(":test_tube::warning:" + text + " research cancelled")
        asyncio.run_coroutine_threadsafe(coro, self.fbot.loop)

class FacBot(commands.Bot):
    # Interacts with discord
    def __init__(self, bridge_id, data_dir, logfile, host):
        super().__init__(['/', ''])
        self.bridge_id = int(bridge_id)
        self.data_dir = data_dir
        self.host = host
        with open(data_dir + "/config/rconpw", "r") as f:
            self.pw = f.readline().strip()
        self.log_in = FacLogHandler(self, data_dir + "/" + logfile)

    async def on_message(self, message):
        if message.author.bot:
            return # don't listen to other bots....
        ctx = await self.get_context(message)

        if ctx.prefix == '/':
            # an actual command
            return await self.invoke(ctx)
        elif ctx.channel.id == self.bridge_id:
            # a chat message
            return await self.send_to_factorio(ctx)

    async def send_to_factorio(self, ctx):
        msg = "Discord:{}: {}".format(ctx.author.display_name, ctx.message.content)
        logger.debug("Msg from discord: \"{}\"".format(msg))
        with MCRcon(self.host, self.pw, 27015) as rcon:
            resp = rcon.command(msg)
            logger.debug("Response from factorio: '%s'", resp)

    async def on_ready(self):
        logger.info("Connected to discord")
    
if __name__ == "__main__":
    logger.info("Starting discord/factorio bridge....")
    fb = FacBot(os.environ['CHANNEL_ID'],
                os.environ["FACTORIO_DATA_DIR_PATH"],
                os.getenv("FACTORIO_LOGFILE", 'factorio-current.log'),
                os.getenv("FACTORIO_HOST", '127.0.0.1'))
    fb.run(os.environ["DISCORD_KEY"])
