from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database import get_db
from sqlalchemy import func
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


@app.post("/primerjava", response_model=schemas.PrimerjavaOut)
def primerjaj_cene(zahteva: schemas.PrimerjavaIn, db: Session = Depends(get_db)):
    rezultati = db.query(
        models.Trgovina.ime.label("ime_trgovina"),
        func.sum(models.Cena.cena).label("skupna_cena")
    ).join(
        models.Cena, models.Cena.trgovina_id == models.Trgovina.id
    ).filter(
        models.Cena.izdelek_id.in_(zahteva.izdelek_ids)
    ).group_by(
        models.Trgovina.ime
    ).all()

    cene_po_trgovinah = [
        schemas.SkupnaCenaTrgovina(ime_trgovina=r.ime_trgovina, skupna_cena=round(float(r.skupna_cena), 2))
        for r in rezultati
    ]

    najcenejsa = min(cene_po_trgovinah, key=lambda x: x.skupna_cena)
    najdrazja = max(cene_po_trgovinah, key=lambda x: x.skupna_cena)
    prihranek = round(najdrazja.skupna_cena - najcenejsa.skupna_cena, 2)

    return schemas.PrimerjavaOut(
        cene_po_trgovinah=cene_po_trgovinah,
        najcenejsa_trgovina=najcenejsa.ime_trgovina,
        prihranek=prihranek
    )