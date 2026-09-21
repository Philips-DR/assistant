"""The assistant: the smallest component in the suite.

It classifies a request, calls a tool, gates anything that writes, and logs what happened.
It owns no domain logic whatsoever -- every hard thing lives inside a tool, behind an MCP
door, where it is tested and cannot drift.
"""
