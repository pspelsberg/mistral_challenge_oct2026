"""Slice 0: Environment Discovery (Section 3)."""

from rogue_agent.features.environment_discovery.models import EnvironmentDiscoveryReport
from rogue_agent.features.environment_discovery.service import discover_environment

__all__ = ["EnvironmentDiscoveryReport", "discover_environment"]
