"""Product schema for the Northlight Outdoors catalog."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    category: str
    price_paise: int
    stock: int
    spec: str

    def to_dict(self) -> dict:
        return asdict(self)
