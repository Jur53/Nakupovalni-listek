"use client";

import { useEffect, useState } from "react";

type Trgovina = {
  id: number;
  ime: string;
};

export default function Home() {
  const [trgovine, setTrgovine] = useState<Trgovina[]>([]);

  useEffect(() => {
    fetch("http://localhost:8000/trgovine")
      .then((res) => res.json())
      .then((data) => setTrgovine(data));
  }, []);

  return (
    <div>
      <h1>Trgovine</h1>
      <ul>
        {trgovine.map((t) => (
          <li key={t.id}>{t.ime}</li>
        ))}
      </ul>
    </div>
  );
}