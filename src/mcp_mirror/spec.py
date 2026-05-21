"""ServerSpec: a single representation of where to find an MCP server.

Captures take a ServerSpec rather than a transport-specific connection object so
the same code path handles both stdio (local subprocess) and streamable HTTP
(remote service like Arcade) servers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ServerSpec:
    kind: Literal["stdio", "http"]
    # stdio-only:
    command: str | None = None
    args: tuple[str, ...] = ()
    # http-only:
    url: str | None = None
    headers: tuple[tuple[str, str], ...] = ()  # frozen for hashability

    @classmethod
    def stdio(cls, command: str, args: list[str] | tuple[str, ...] = ()) -> "ServerSpec":
        return cls(kind="stdio", command=command, args=tuple(args))

    @classmethod
    def http(cls, url: str, headers: dict[str, str] | None = None) -> "ServerSpec":
        return cls(
            kind="http",
            url=url,
            headers=tuple(sorted((headers or {}).items())),
        )

    @property
    def headers_dict(self) -> dict[str, str]:
        return dict(self.headers)
