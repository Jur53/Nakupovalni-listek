from pydantic import BaseModel

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