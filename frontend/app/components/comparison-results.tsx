import { type Ref } from "react";
import { formatEur, type Comparison, type SplitItem } from "@/lib/api";
import { CheckIcon, StoreIcon } from "@/app/components/icons";

type ComparisonResultsProps = {
  comparison: Comparison;
  headingRef: Ref<HTMLHeadingElement>;
};

function groupByStore(items: SplitItem[]): Array<[string, SplitItem[]]> {
  const groups = new Map<string, SplitItem[]>();
  for (const item of items) groups.set(item.store, [...(groups.get(item.store) ?? []), item]);
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right, "sl"));
}

export function ComparisonResults({ comparison, headingRef }: ComparisonResultsProps) {
  const storeGroups = groupByStore(comparison.splitItems);

  return (
    <section className="results-section" aria-labelledby="results-title">
      <p className="sr-only" role="status" aria-live="polite">Primerjava cen je končana.</p>
      <div className="results-heading">
        <div>
          <span className="eyebrow">3. Rezultat</span>
          <h2 ref={headingRef} id="results-title" tabIndex={-1}>Vaš najugodnejši nakup</h2>
        </div>
        <span className="result-stamp"><CheckIcon /> Izračunano</span>
      </div>

      <div className="winner-grid">
        <div className="winner-card">
          <span>Vse v eni trgovini</span>
          {comparison.completeBasketAvailable ? (
            <>
              <strong>{comparison.cheapestStore}</strong>
              <p>Prihranek do <b>{formatEur(comparison.savings ?? 0)}</b> glede na najdražjo možnost.</p>
            </>
          ) : (
            <>
              <strong>Ni na voljo</strong>
              <p>Nobena trgovina nima cen za vse izbrane izdelke.</p>
            </>
          )}
        </div>
        <div className="split-total-card">
          <span>Razdeljen nakup</span>
          <strong>{formatEur(comparison.splitTotal)}</strong>
          <p>
            {comparison.additionalSavings === null
              ? "Najugodnejša razdelitev po trgovinah."
              : `Še ${formatEur(comparison.additionalSavings)} dodatnega prihranka.`}
          </p>
        </div>
      </div>

      <div className="result-columns">
        <div>
          <h3>Primerjava trgovin</h3>
          {comparison.storeTotals.length === 0 ? (
            <p className="inline-empty">Primerjava trgovin ni na voljo.</p>
          ) : (
            <ol className="store-totals">
              {comparison.storeTotals.map((entry, index) => (
                <li key={`${entry.store}-${index}`}>
                  <span className="rank">{String(index + 1).padStart(2, "0")}</span>
                  <span>{entry.store}</span>
                  <strong>{formatEur(entry.total)}</strong>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div>
          <h3>Razdeljen nakup po trgovinah</h3>
          {storeGroups.length === 0 ? (
            <p className="inline-empty">Razdeljen seznam ni na voljo.</p>
          ) : (
            <div className="split-groups">
              {storeGroups.map(([store, items]) => (
                <section className="split-store" key={store} aria-label={`Nakup v trgovini ${store}`}>
                  <h4><StoreIcon /> {store}</h4>
                  <ul>
                    {items.map((item, index) => (
                      <li key={`${item.productId}-${index}`}>
                        <span>
                          <strong>{item.name}</strong>
                          <small>{item.quantity} × {formatEur(item.unitPrice)}</small>
                        </span>
                        <b>{formatEur(item.total)}</b>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
