from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PositiveInt, field_serializer, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MoneyModel(BaseModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_decimals(self, value):
        return format(value, ".2f") if isinstance(value, Decimal) else value


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: int
    email: EmailStr
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TrgovinaOut(ORMModel):
    id: int
    ime: str


class NajcenejsaPonudba(MoneyModel):
    trgovina_id: int
    ime_trgovina: str
    cena: Decimal
    datum_zajema: date


class IzdelekOut(ORMModel):
    id: int
    ime: str
    kategorija: str | None
    kategorija_id: int | None
    kategorija_pot: list[str]
    enota: str | None
    najcenejsa_ponudba: NajcenejsaPonudba
    ponudbe: list[NajcenejsaPonudba]


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    product_count: int
    children: list["CategoryOut"]


class IzdelkiPageOut(BaseModel):
    items: list[IzdelekOut]
    total: int
    offset: int
    limit: int
    categories: list[str]
    category_tree: list[CategoryOut]


class CenaDetajlOut(MoneyModel):
    izdelek_id: int
    ime_izdelek: str
    trgovina_id: int
    ime_trgovina: str
    cena: Decimal
    datum_zajema: date


class ZahtevanIzdelek(BaseModel):
    izdelek_id: int = Field(gt=0)
    kolicina: int = Field(default=1, gt=0, le=10_000)


class UniqueItemsModel(BaseModel):
    items: list[ZahtevanIzdelek] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_products(self):
        ids = [item.izdelek_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("izdelek_id must be unique; combine duplicate quantities")
        return self


class PrimerjavaIn(UniqueItemsModel):
    trgovina_ids: list[PositiveInt] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_stores(self):
        if self.trgovina_ids and len(self.trgovina_ids) != len(set(self.trgovina_ids)):
            raise ValueError("trgovina_ids must be unique")
        return self


class SkupnaCenaTrgovina(MoneyModel):
    trgovina_id: int
    ime_trgovina: str
    skupna_cena: Decimal


class IzdelekNajcenejsi(MoneyModel):
    izdelek_id: int
    ime_izdelek: str
    trgovina_id: int
    ime_trgovina: str
    kolicina: int
    cena_na_enoto: Decimal
    skupna_cena: Decimal


class PrimerjavaOut(MoneyModel):
    celoten_nakup_na_voljo: bool
    cene_po_trgovinah: list[SkupnaCenaTrgovina]
    najcenejsa_trgovina_id: int | None
    najcenejsa_trgovina: str | None
    prihranek: Decimal | None
    razdeljen_seznam: list[IzdelekNajcenejsi]
    skupna_cena_razdeljeno: Decimal
    dodatni_prihranek: Decimal | None


class SeznamIn(UniqueItemsModel):
    ime: str = Field(min_length=1, max_length=100)

    @field_validator("ime")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ime must not be blank")
        return value


class SeznamOut(ORMModel):
    id: int
    ime: str
    ustvarjen: datetime


class SeznamIzdelekIn(BaseModel):
    izdelek_id: int = Field(gt=0)
    kolicina: int = Field(default=1, gt=0, le=10_000)


class SeznamIzdelekOut(ORMModel):
    id: int
    seznam_id: int
    izdelek_id: int
    kolicina: int


class SeznamIzdelekDetajl(BaseModel):
    izdelek_id: int
    ime_izdelek: str
    kategorija: str | None
    enota: str | None
    kolicina: int


class SeznamDetajlOut(BaseModel):
    id: int
    ime: str
    ustvarjen: datetime
    izdelki: list[SeznamIzdelekDetajl]
