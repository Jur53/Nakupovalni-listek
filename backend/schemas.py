from pydantic import BaseModel
from datetime import date


class TrgovinaOut(BaseModel):
    id: int
    ime: str

    class Config:
        from_attributes = True

class IzdelekOut(BaseModel):
    id: int
    ime: str
    kategorija: str | None
    enota: str | None

    class Config:
        from_attributes = True

class CenaDetajlOut(BaseModel):
    ime_izdelek: str
    ime_trgovina: str
    cena: float
    datum_zajema: date

    class Config:
        from_attributes = True