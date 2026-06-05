"""Allow running as: python -m v2"""
from .main import main
import asyncio

asyncio.run(main())
