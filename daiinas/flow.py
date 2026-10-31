"""Future data adapters only. No flow signal is implemented or backtested."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BookSnapshot:
    symbol: str
    timestamp: int
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class AggressiveTrade:
    symbol: str
    timestamp: int
    price: float
    quantity: float
    buyer_is_maker: bool


class FlowSource(Protocol):
    def book(self, symbol: str) -> BookSnapshot: ...
    def trades(self, symbol: str, start: int, end: int) -> list[AggressiveTrade]: ...
