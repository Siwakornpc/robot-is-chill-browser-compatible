# build_db.py | creates robot.db without running the Discord bot.
import asyncio
import importlib

from headless import HeadlessBot


class PrintCtx:
    """The loader commands report progress through ctx.send."""
    async def send(self, content="", **kwargs):
        print(content)


async def main():
    bot = HeadlessBot("robot.db")

    await bot.db.connect(bot.db_path)          # also creates the tables

    loading = importlib.import_module("src.cogs.loading")
    cog = loading.LoadingCog(bot)
    ctx = PrintCtx()

    print("Loading tiles from data/custom/*.toml ...")

    await cog.load_custom_tiles()
    await loading.LoadingCog.loadpalettes.callback(cog, ctx)
    await loading.LoadingCog.loadletters.callback(cog, ctx)

    conn = bot.db.conn

    assert conn is not None, "database is not connected"

    async with conn.cursor() as cur:
        for table in ("tiles", "palettes", "letters"):
            await cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = await cur.fetchone()               # None only if the query returned nothing
            print(f"  {table}: {row[0] if row else 0} rows")
            
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())