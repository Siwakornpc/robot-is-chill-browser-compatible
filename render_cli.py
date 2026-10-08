# render_cli.py | render a scene to an image file without Discord.

import argparse
import asyncio
import re
import sys
import time
from datetime import datetime

from headless import HeadlessBot, RenderError, render


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", help='e.g. "=t baba keke wall" or "=r baba is you"')
    ap.add_argument("-o", "--out", help="output name, no extension")
    args = ap.parse_args()

    scene, rule = args.scene.strip(), False
    m = re.match(r"^=?(t|tile|r|rule)\s+(.*)$", scene, re.S)

    if m:
        rule = m.group(1) in ("r", "rule")
        scene = m.group(2)

    bot = HeadlessBot("robot.db")

    await bot.start()
    try:
        if "[" in scene and not bot.macros_enabled:
            raise RenderError("Macros aren't available here (macrosia_glue is not installed).")
        
        t0 = time.perf_counter()
        data, ext = await render(bot, scene, rule)
        output_name = args.out or datetime.now().strftime("render_%Y-%m-%d_%H.%M.%S")
        path = f"{output_name}.{ext}"

        with open(path, "wb") as fp:
            fp.write(data)

        print(f"Saved {path} ({len(data)} bytes, {time.perf_counter() - t0:.2f}s)")
    except RenderError as err:
        sys.exit("Render error: " + " ".join(str(err).split()))   # one line, so the API can read it
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())