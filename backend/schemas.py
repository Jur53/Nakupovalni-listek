from pydantic import BaseModel
from datetime import date
from datetime import datetime


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

class PrimerjavaIn(BaseModel):
    izdelek_ids: list[int]

class SkupnaCenaTrgovina(BaseModel):
    ime_trgovina: str
    skupna_cena: float

class IzdelekNajcenejsi(BaseModel):
    ime_izdelek: str
    ime_trgovina: str
    cena: float

class PrimerjavaOut(BaseModel):
    cene_po_trgovinah: list[SkupnaCenaTrgovina]
    najcenejsa_trgovina: str 
    prihranek: float 
    razdeljen_seznam: list[IzdelekNajcenejsi]
    skupna_cena_razdeljeno: float
    dodatni_prihranek: float

class SeznamIn(BaseModel):
    ime: str | None = None

class SeznamOut(BaseModel):
    id: int
    ime: str | None
    ustvarjen: datetime

    class Config:
        from_attributes = True

class SeznamIzdelekIn(BaseModel):
    izdelek_id: int
    kolicina: int = 1

class SeznamIzdelekOut(BaseModel):
    id: int
    seznam_id: int
    izdelek_id: int
    kolicina: int

    class Config:
        from_attributes = True

class SeznamIzdelekDetajl(BaseModel):
    ime_izdelek: str
    kategorija: str | None
    enota: str | None
    kolicina: int

class SeznamDetajlOut(BaseModel):
    id: int
    ime: str | None
    ustvarjen: datetime
    izdelki: list[SeznamIzdelekDetajl]