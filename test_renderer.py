import asyncio

from src.tile import TileSkeleton


async def main():
    print("Parsing baba...")

    tile = await TileSkeleton.parse(
        None,
        "baba"
    )

    print(tile)


asyncio.run(main())