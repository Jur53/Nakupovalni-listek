from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Date, DateTime
from database import Base


DATABASE_URL = "postgresql://tomaz@localhost/nakupovalni_listek"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def geet_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Trgovina(Base):
    __tablename__ = "trgovina"

    id = Column(Integer, primary_key=True)
    ime = Column(String(100), nullable=False, unique=True)


