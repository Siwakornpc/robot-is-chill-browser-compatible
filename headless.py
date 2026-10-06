# Needs python 3.11+
 
import asyncio
import importlib
import signal
import sys
import types
from pathlib import Path
from typing import Any

if "webhooks" not in sys.modules:
    try:
        import webhooks  # type: ignore  # noqa: F401  (use the real one if the user has it)
    except ModuleNotFoundError:
        stub = types.ModuleType("webhooks")
        setattr(stub, "logging_id", 0)
        sys.modules["webhooks"] = stub

if not hasattr(signal, "alarm"):
    setattr(signal, "alarm", lambda seconds: 0)

import discord  # noqa: E402
from PIL import ImageDraw as _PilImageDraw  # noqa: E402
from PIL import features as _pil_features  # noqa: E402

if not _pil_features.check("raqm"):
    _original_multiline_text = _PilImageDraw.ImageDraw.multiline_text

    def _multiline_text_without_features(self, *args, features=None, **kwargs):
        return _original_multiline_text(self, *args, **kwargs)

    setattr(_PilImageDraw.ImageDraw, "multiline_text", _multiline_text_without_features)

from src.db import Database  # noqa: E402

class RenderError(Exception):
    """Raised when the renderer reports a user-facing error (bad tile, etc.)."""

class HeadlessBot:
    """Just enough of `commands.Bot` for the cogs the renderer touches."""

    def __init__(self, db_path: str = "robot.db"):
        self.db_path = db_path
        self.db = Database(self)
        self.embed_color = discord.Color(12877055)
        self.loading = False
        self.baba_loaded = True
        self.macros = {}
        self.macro_handler: Any = None
        self.macros_enabled = False
        self.renderer: Any = None
        self.flags: Any = None
        self.variants: Any = None

    async def is_owner(self, user):
        return False

    async def start(self):
        await self.db.connect(self.db_path)

        for name in ("src.cogs.render", "src.cogs.flags", "src.cogs.variants"):
            await importlib.import_module(name).setup(self)
        try:
            import macrosia_glue  # type: ignore  # noqa: F401
        except ModuleNotFoundError:
            pass
        else:
            await importlib.import_module("src.cogs.macros").setup(self)
            macrosia_glue.connect_to_db(self.db_path)
            self.macro_handler.update_macros()
            self.macros_enabled = True

    async def close(self):
        await self.db.close()

class mctx:
    """Stands in for the Discord `ctx` that render_tiles expects."""
    fake = True
    message = None
    silent = False
    ephemeral = False

    def __init__(self, bot):
        self.bot = bot
        self.result = None
        self.sent = []

    async def typing(self):
        pass

    async def send(self, content="", **kwargs):
        self.sent.append(content)

    async def reply(self, content="", *, file=None, **kwargs):
        if file is not None:
            ext = Path(file.filename).suffix.lstrip(".") or "png"
            file.fp.seek(0)
            self.result = (file.fp.read(), ext)
        else:
            self.sent.append(content)

    async def error(self, msg, **kwargs):
        raise RenderError(msg)


def friendly_error(err: Exception):
    """Mirror src/cogs/errorhandler.py: turn the errors the Discord bot would
    show to the user into plain messages. Returns None for real bugs."""

    from src import errors
    import numpy

    def arg(index: int, default=None):
        """err.args[index], or default when it is missing."""
        return err.args[index] if len(err.args) > index else default

    if isinstance(err, (AssertionError, NotImplementedError)):
        first = arg(0)
        return str(first) if first else None
    
    if isinstance(err, errors.UnknownVariant):
        return f"The variant `{arg(0, '')}` doesn't exist or is malformed."
    
    if isinstance(err, errors.InvalidFlagError):
        return f"A flag failed to parse: {err}"
    
    if isinstance(err, errors.TimeoutError):
        return "The command took too long and was timed out."
    
    if isinstance(err, errors.OverlayNotFound):
        return f"The overlay `{err}` does not exist."
    
    if isinstance(err, numpy.linalg.LinAlgError):
        return "The given warp points are unsolvable."
    
    if isinstance(err, errors.MacroError):
        text = f"Macro execution failed: {arg(0, 'unknown error')}"
        trace = arg(1)
        if trace:
            text += " | " + " <- ".join(str(f).strip() for f in list(trace)[:3])
        return text
    return None


async def render(bot: HeadlessBot, objects: str, rule: bool = False):
    """Render a scene string. Returns (image_bytes, 'png' | 'gif')."""

    cog_module = importlib.import_module("src.cogs.global")
    cog = cog_module.GlobalCog(bot)
    ctx = mctx(bot)

    try:
        await cog.render_tiles(ctx, objects=objects, rule=rule)
    except RenderError:
        raise
    except Exception as err:
        message = friendly_error(err)
        if message is None:
            raise                      # a genuine bug: keep the traceback
        raise RenderError(message) from None
    
    if ctx.result is None:
        raise RenderError("Nothing was rendered.")
    
    return ctx.result