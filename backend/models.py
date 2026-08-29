from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Date, DateTime
from database import Base


class Trgovina(Base):
    __tablename__ = "trgovine"

    id = Column(Integer, primary_key=True)
    ime = Column(String(100), nullable=False, unique=True)


class Izdelek(Base):
    __tablename__ = "izdelki"

    id = Column(Integer, primary_key=True)
    ime = Column(String(200), nullable=False)
    kategorija = Column(String(100))
    enota = Column(String(20))


class Cena(Base):
    __tablename__ = "cene"

    id = Column(Integer, primary_key=True)
    izdelek_id = Column(Integer, ForeignKey("izdelki.id"), nullable=False)
    trgovina_id = Column(Integer, ForeignKey("trgovine.id"), nullable=False)
    cena = Column(Numeric(6, 2), nullable=False)
    datum_zajema = Column(Date, nullable=False)


class Seznam(Base):
    __tablename__ = "seznami"

    id = Column(Integer, primary_key=True)
    ime = Column(String(100))
    ustvarjen = Column(DateTime, nullable=False)

class Seznam_izdelek(Base):
    __tablename__ = "seznam_izdelki"

    id = Column(Integer, primary_key=True)
    seznam_id = Column(Integer, ForeignKey("seznami.id"), nullable=False)
    izdelek_id = Column(Integer, ForeignKey("izdelki.id"), nullable=False)
    kolicina = Column(Integer, nullable=False, default=1)

