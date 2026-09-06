"use client";

import { useEffect, useState } from "react";

type Trgovina = {
  id: number;
  ime: string;
};

type Izdelek = {
  id: number;
  ime: string;
  kategorija: string | null;
  enota: string | null;
};

type SkupnaCenaTrgovina = {
  ime_trgovina: string;
  skupna_cena: number;
};

type IzdelekNajcenejsi = {
  ime_izdelek: string;
  ime_trgovina: string;
  cena: number;
};

type PrimerjavaOut = {
  cene_po_trgovinah: SkupnaCenaTrgovina[];
  najcenejsa_trgovina: string;
  prihranek: number;
  razdeljen_seznam: IzdelekNajcenejsi[];
  skupna_cena_razdeljeno: number;
  dodatni_prihranek: number;
};

export default function Home() {
  const [trgovine, setTrgovine] = useState<Trgovina[]>([]);
  const [izdelki, setIzdelki] = useState<Izdelek[]>([]);
  const [izbrani, setIzbrani] = useState<number[]>([]);
  const [rezultat, setRezultat] = useState<PrimerjavaOut | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/trgovine")
      .then((res) => res.json())
      .then((data) => setTrgovine(data));
  }, []);

  useEffect(() => {
    fetch("http://localhost:8000/izdelki")
      .then((res) => res.json())
      .then((data) => setIzdelki(data));
  }, []);

  function preklopiIzbiro(id: number) {
    if (izbrani.includes(id)) {
      setIzbrani(izbrani.filter((x) => x !== id));
    } else {
      setIzbrani([...izbrani, id]);
    }
  }

  function primerjajCene() {
    fetch("http://localhost:8000/primerjava", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ izdelek_ids: izbrani }),
    })
      .then((res) => res.json())
      .then((data) => setRezultat(data));
  }

  return (
    <div className="p-8 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Trgovine</h1>
      <ul className="mb-8 space-y-1">
        {trgovine.map((t) => (
          <li key={t.id} className="text-gray-400">
            {t.ime}
          </li>
        ))}
      </ul>

      <h1 className="text-2xl font-bold mb-4">Izdelki</h1>
      <ul className="mb-6 space-y-2">
        {izdelki.map((i) => (
          <li key={i.id} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={izbrani.includes(i.id)}
              onChange={() => preklopiIzbiro(i.id)}
              className="w-4 h-4"
            />
            <span>{i.ime}</span>
          </li>
        ))}
      </ul>

      <button
        onClick={primerjajCene}
        disabled={izbrani.length === 0}
        className="px-4 py-2 rounded-lg bg-blue-600 text-white font-medium disabled:bg-gray-300 disabled:text-gray-500 hover:bg-blue-700 disabled:cursor-not-allowed"
      >
        Primerjaj cene
      </button>

      {rezultat && (
        <div className="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
          <h2 className="text-xl font-semibold mb-3 text-gray-900">Rezultat</h2>
          <ul className="space-y-1 mb-4">
            {rezultat.cene_po_trgovinah.map((c) => (
              <li key={c.ime_trgovina} className="text-gray-900">
                {c.ime_trgovina}: <span className="font-medium">{c.skupna_cena}€</span>
              </li>
            ))}
          </ul>
          <p className="text-green-700 font-medium">
            Najcenejša trgovina: {rezultat.najcenejsa_trgovina} (prihranek {rezultat.prihranek}€)
          </p>
          <p className="text-gray-600 mt-1">
            Razdeljen nakup: {rezultat.skupna_cena_razdeljeno}€ (dodatni prihranek {rezultat.dodatni_prihranek}€)
          </p>
        </div>
      )}
    </div>
  );
}