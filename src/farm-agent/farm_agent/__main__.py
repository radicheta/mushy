"""
farm_agent/__main__.py -- `python -m farm_agent` entry point (FND-01).

Thin wrapper: all logic lives in boot.main().
"""

import asyncio

from farm_agent.boot import main

asyncio.run(main())
