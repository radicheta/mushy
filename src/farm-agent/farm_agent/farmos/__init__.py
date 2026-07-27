"""
farm_agent/farmos -- farmOS write-path package.

Exposes create_farmos_client at the package root for convenience.
"""

from farm_agent.farmos.client import create_farmos_client

__all__ = ["create_farmos_client"]
