from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas

app = FastAPI()

@app.get("/trgovine", response_model=list[schemas.TrgovinaOut])
def get_trgovine(db: Session = Depends(get_db)):
    return db.query(models.Trgovina).all()

@app.get("/izdelki", response_model=list[schemas.IzdelekOut])
def get_izdelki(db: Session = Depends(get_db)):
    return db.query(models.Izdelek).all()

@app.get("/cene", response_model=list[schemas.CenaDetajlOut])
def get_cene(db: Session = Depends(get_db)):
    return db.query(
        models.Izdelek.ime.label("ime_izdelek"),
        models.Trgovina.ime.label("ime_trgovina"),
        models.Cena.cena,
        models.Cena.datum_zajema
    ).join(models.Izdelek, models.Cena.izdelek_id == models.Izdelek.id
    ).join(models.Trgovina, models.Cena.trgovina_id == models.Trgovina.id
    ).all()
