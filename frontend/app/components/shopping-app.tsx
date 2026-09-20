"use client";

import { FormEvent, useDeferredValue, useEffect, useRef, useState } from "react";
import { AuthPanel } from "@/app/components/auth-panel";
import { ComparisonResults } from "@/app/components/comparison-results";
import { ArrowIcon, BasketIcon, CheckIcon } from "@/app/components/icons";
import { ProductPicker } from "@/app/components/product-picker";
import {
  ApiError,
  api,
  getErrorMessage,
  type CategoryNode,
  type Comparison,
  type Product,
  type SavedList,
  type SelectedItem,
  type Store,
  type User,
} from "@/lib/api";

type AsyncState = "idle" | "loading" | "success" | "error";

function categoryTreeContains(nodes: CategoryNode[], categoryId: number): boolean {
  return nodes.some((node) =>
    node.id === categoryId || categoryTreeContains(node.children, categoryId),
  );
}

export function ShoppingApp() {
  const [stores, setStores] = useState<Store[]>([]);
  const [selectedStoreIds, setSelectedStoreIds] = useState<number[]>([]);
  const [storesLoading, setStoresLoading] = useState(true);
  const [storesError, setStoresError] = useState<string | null>(null);
  const [storesAttempt, setStoresAttempt] = useState(0);
  const [products, setProducts] = useState<Product[]>([]);
  const [catalogState, setCatalogState] = useState<AsyncState>("loading");
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [selection, setSelection] = useState<Record<number, number>>({});
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [categoryTree, setCategoryTree] = useState<CategoryNode[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [productPage, setProductPage] = useState(0);
  const [productsLoading, setProductsLoading] = useState(false);
  const productPageSize = 24;

  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonState, setComparisonState] = useState<AsyncState>("idle");
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const comparisonAbort = useRef<AbortController | null>(null);
  const comparisonRequest = useRef(0);
  const comparisonHeading = useRef<HTMLHeadingElement>(null);
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null);

  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [sessionAttempt, setSessionAttempt] = useState(0);
  const [savedLists, setSavedLists] = useState<SavedList[]>([]);
  const [listsState, setListsState] = useState<AsyncState>("idle");
  const [listsError, setListsError] = useState<string | null>(null);
  const [listName, setListName] = useState("");
  const [saveState, setSaveState] = useState<AsyncState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadStores() {
      setStoresLoading(true);
      setStoresError(null);
      setCatalogState("loading");
      try {
        const nextStores = await api.getStores(controller.signal);
        if (nextStores.length === 0) {
          throw new ApiError("Trgovine trenutno niso na voljo.", 503);
        }
        setCategoryId(null);
        setCategoryTree([]);
        setProductPage(0);
        setStores(nextStores);
        setSelectedStoreIds((current) => {
          const available = new Set(nextStores.map((store) => store.id));
          const retained = current.filter((storeId) => available.has(storeId));
          return retained.length
            ? retained.sort((left, right) => left - right)
            : nextStores.map((store) => store.id).sort((left, right) => left - right);
        });
        setStoresError(null);
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        const message = getErrorMessage(reason);
        setStores([]);
        setSelectedStoreIds([]);
        setStoresError(message);
        setCatalogError(message);
        setCatalogState("error");
      } finally {
        if (!controller.signal.aborted) setStoresLoading(false);
      }
    }
    void loadStores();
    return () => controller.abort();
  }, [storesAttempt]);

  useEffect(() => {
    if (storesLoading || storesError || selectedStoreIds.length === 0) return;
    const controller = new AbortController();
    async function loadCatalog() {
      setProductsLoading(true);
      try {
        const nextProducts = await api.getProducts(
          {
            search: deferredSearch,
            categoryId,
            storeIds: selectedStoreIds,
            offset: productPage * productPageSize,
            limit: productPageSize,
          },
          controller.signal,
        );
        setProducts(nextProducts.items);
        setCategoryTree(nextProducts.categoryTree);
        setProductTotal(nextProducts.total);
        setCatalogState("success");
        setCatalogError(null);
        if (categoryId !== null && !categoryTreeContains(nextProducts.categoryTree, categoryId)) {
          setCategoryId(null);
          setProductPage(0);
        }
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setCatalogState("error");
        setCatalogError(getErrorMessage(reason));
      } finally {
        if (!controller.signal.aborted) setProductsLoading(false);
      }
    }
    void loadCatalog();
    return () => controller.abort();
  }, [catalogAttempt, categoryId, deferredSearch, productPage, selectedStoreIds, storesError, storesLoading]);

  useEffect(() => {
    const controller = new AbortController();
    async function restoreSession() {
      setAuthLoading(true);
      setAuthError(null);
      try {
        const currentUser = await api.me(controller.signal);
        setUser(currentUser);
        try {
          setListsState("loading");
          setSavedLists(await api.getSavedLists(controller.signal));
          setListsState("success");
          setListsError(null);
        } catch (reason) {
          if (!(reason instanceof DOMException && reason.name === "AbortError")) {
            if (reason instanceof ApiError && reason.status === 401) {
              clearAuthenticatedState();
            } else {
              setListsState("error");
              setListsError(getErrorMessage(reason));
            }
          }
        }
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setUser(null);
        if (!(reason instanceof ApiError && reason.status === 401)) setAuthError(getErrorMessage(reason));
      } finally {
        if (!controller.signal.aborted) setAuthLoading(false);
      }
    }
    void restoreSession();
    return () => controller.abort();
  }, [sessionAttempt]);

  useEffect(() => () => comparisonAbort.current?.abort(), []);

  useEffect(() => {
    if (comparisonState === "success") comparisonHeading.current?.focus();
  }, [comparisonState]);

  const selectedItems: SelectedItem[] = Object.entries(selection).map(([productId, quantity]) => ({
    izdelek_id: Number(productId),
    kolicina: quantity,
  }));
  const selectedUnits = selectedItems.reduce((sum, item) => sum + item.kolicina, 0);

  function invalidateComparison() {
    comparisonAbort.current?.abort();
    comparisonRequest.current += 1;
    setComparison(null);
    setComparisonState("idle");
    setComparisonError(null);
    setSaveMessage(null);
  }

  function toggleProduct(productId: number) {
    invalidateComparison();
    setSelectionMessage(null);
    setSelection((current) => {
      const next = { ...current };
      if (next[productId]) delete next[productId];
      else next[productId] = 1;
      return next;
    });
  }

  function changeQuantity(productId: number, quantity: number) {
    invalidateComparison();
    setSelectionMessage(null);
    setSelection((current) => ({ ...current, [productId]: quantity }));
  }

  function toggleStore(storeId: number) {
    invalidateComparison();
    setCategoryId(null);
    setCategoryTree([]);
    setProductPage(0);
    setProducts([]);
    setSelection({});
    if (selectedItems.length > 0) setSelectionMessage("Izbor izdelkov je bil zaradi spremembe trgovin počiščen.");
    setSelectedStoreIds((current) => {
      if (!current.includes(storeId)) return [...current, storeId].sort((left, right) => left - right);
      return current.length === 1 ? current : current.filter((id) => id !== storeId);
    });
  }

  function selectAllStores() {
    invalidateComparison();
    setCategoryId(null);
    setCategoryTree([]);
    setProductPage(0);
    setProducts([]);
    setSelection({});
    if (selectedItems.length > 0) setSelectionMessage("Izbor izdelkov je bil zaradi spremembe trgovin počiščen.");
    setSelectedStoreIds(stores.map((store) => store.id).sort((left, right) => left - right));
  }

  async function comparePrices() {
    if (comparisonState === "loading" || selectedItems.length === 0) return;
    const controller = new AbortController();
    comparisonAbort.current?.abort();
    comparisonAbort.current = controller;
    const requestId = ++comparisonRequest.current;
    const items = selectedItems.map((item) => ({ ...item }));
    setComparisonState("loading");
    setComparisonError(null);
    setComparison(null);

    try {
      const result = await api.compare(items, selectedStoreIds, controller.signal);
      if (requestId !== comparisonRequest.current) return;
      setComparison(result);
      setComparisonState("success");
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (requestId !== comparisonRequest.current) return;
      setComparisonError(getErrorMessage(reason));
      setComparisonState("error");
    }
  }

  async function loadSavedLists() {
    if (listsState === "loading") return;
    setListsState("loading");
    try {
      setSavedLists(await api.getSavedLists());
      setListsState("success");
      setListsError(null);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) clearAuthenticatedState();
      setListsState("error");
      setListsError(getErrorMessage(reason));
    }
  }

  function handleAuthenticated(currentUser: User) {
    setUser(currentUser);
    setAuthLoading(false);
    setAuthError(null);
    setSaveMessage("Prijava je uspela. Seznam lahko zdaj shranite.");
    void loadSavedLists();
  }

  async function handleLogout() {
    await api.logout();
    clearAuthenticatedState();
    setSaveState("success");
    setSaveMessage("Uspešno ste se odjavili.");
  }

  function clearAuthenticatedState() {
    setUser(null);
    setSavedLists([]);
    setListsState("idle");
    setListsError(null);
  }

  async function saveList(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = listName.trim();
    if (!user || !trimmedName || trimmedName.length > 100 || selectedItems.length === 0 || saveState === "loading") {
      return;
    }
    setSaveState("loading");
    setSaveMessage(null);
    try {
      const saved = await api.saveList(trimmedName, selectedItems);
      setSavedLists((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setListName("");
      setSaveState("success");
      setSaveMessage(`Seznam »${saved.name}« je shranjen.`);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        clearAuthenticatedState();
      }
      setSaveState("error");
      setSaveMessage(getErrorMessage(reason));
    }
  }

  return (
    <>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Pametna košarica, na vrh">
          <span className="brand-mark"><BasketIcon /></span>
          <span>Pametna <b>košarica</b></span>
        </a>
        <AuthPanel
          authLoading={authLoading}
          authError={authError}
          user={user}
          onAuthenticated={handleAuthenticated}
          onLogout={handleLogout}
          onRetrySession={() => setSessionAttempt((value) => value + 1)}
        />
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="page-title">
          <div className="hero-copy">
            <span className="eyebrow">Primerjaj. Razdeli. Prihrani.</span>
            <h1 id="page-title">Manj ugibanja.<br /><em>Več v košarici.</em></h1>
            <p>
              Sestavite nakupovalni seznam in v nekaj sekundah preverite, kje je celoten nakup najugodnejši.
            </p>
            <a className="hero-link" href="#izdelki">Začni primerjavo <ArrowIcon /></a>
          </div>
          <aside className="store-board" aria-label="Vključene trgovine">
            <div className="board-pin" aria-hidden="true" />
            <div className="board-heading">
              <span className="board-label">Cene preverjamo pri</span>
              <button
                type="button"
                disabled={stores.length === 0 || selectedStoreIds.length === stores.length}
                onClick={selectAllStores}
              >
                Izberi vse
              </button>
            </div>
            {storesLoading ? (
              <p role="status">Nalaganje trgovin …</p>
            ) : storesError ? (
              <div className="store-error" role="alert">
                <p>{storesError}</p>
                <button type="button" onClick={() => setStoresAttempt((value) => value + 1)}>Poskusi znova</button>
              </div>
            ) : stores.length ? (
              <ul>
                {stores.map((store) => {
                  const checked = selectedStoreIds.includes(store.id);
                  return (
                    <li key={store.id} className={checked ? "is-active" : ""}>
                      <label>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={checked && selectedStoreIds.length === 1}
                          onChange={() => toggleStore(store.id)}
                        />
                        <span aria-hidden="true"><CheckIcon /></span>
                        {store.name}
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p>Trgovine še niso na voljo.</p>
            )}
            <small>{selectedStoreIds.length} od {stores.length} trgovin v primerjavi.</small>
            {selectionMessage && <p className="sr-only" role="status">{selectionMessage}</p>}
          </aside>
        </section>

        <section className="workspace" id="izdelki" aria-label="Priprava primerjave">
          {catalogState === "loading" && (
            <div className="state-panel" role="status">
              <span className="spinner" aria-hidden="true" />
              <h2>Nalagamo sveže podatke</h2>
              <p>Pripravljamo izdelke in trgovine za primerjavo.</p>
            </div>
          )}

          {catalogState === "error" && (
            <div className="state-panel error-panel" role="alert">
              <h2>Izdelkov ni bilo mogoče naložiti</h2>
              <p>{catalogError}</p>
              <button
                className="secondary-button"
                type="button"
                onClick={() => {
                  setCatalogState("loading");
                  if (storesError) setStoresAttempt((value) => value + 1);
                  else setCatalogAttempt((value) => value + 1);
                }}
              >
                Poskusi znova
              </button>
            </div>
          )}

          {catalogState === "success" && (
            <div className="workspace-grid">
              <ProductPicker
                products={products}
                selection={selection}
                 search={search}
                 categoryId={categoryId}
                 categoryTree={categoryTree}
                 total={productTotal}
                 page={productPage}
                 pageSize={productPageSize}
                 loading={productsLoading}
                 onSearchChange={(value) => {
                    setSearch(value.slice(0, 100));
                   setProductPage(0);
                 }}
                 onCategoryChange={(value) => {
                   setCategoryId(value);
                   setProductPage(0);
                 }}
                 onPageChange={setProductPage}
                onToggle={toggleProduct}
                onQuantityChange={changeQuantity}
              />

              <aside className="action-column" aria-labelledby="summary-title">
                <div className="summary-card">
                  <span className="eyebrow">2. Povzetek</span>
                  <h2 id="summary-title">Vaš seznam</h2>
                  <dl>
                    <div><dt>Izbranih izdelkov</dt><dd>{selectedItems.length}</dd></div>
                    <div><dt>Skupna količina</dt><dd>{selectedUnits}</dd></div>
                    <div><dt>Trgovin v primerjavi</dt><dd>{selectedStoreIds.length}</dd></div>
                  </dl>
                  <button
                    className="primary-button compare-button"
                    type="button"
                    disabled={selectedItems.length === 0 || selectedStoreIds.length === 0 || comparisonState === "loading"}
                    onClick={() => void comparePrices()}
                  >
                    {comparisonState === "loading" ? "Primerjam cene …" : "Primerjaj cene"}
                    {comparisonState !== "loading" && <ArrowIcon />}
                  </button>
                  {selectedItems.length === 0 && <p className="button-help">Za primerjavo izberite vsaj en izdelek.</p>}
                  {comparisonState === "loading" && <p className="sr-only" role="status">Primerjava cen poteka.</p>}
                  {comparisonError && (
                    <div className="action-error" role="alert">
                      <p>{comparisonError}</p>
                      <button type="button" onClick={() => void comparePrices()}>Poskusi znova</button>
                    </div>
                  )}
                </div>

                <form className="save-card" onSubmit={saveList}>
                  <h2>Shranite za naslednjič</h2>
                  <label htmlFor="list-name">Ime seznama</label>
                  <input
                    id="list-name"
                    value={listName}
                    maxLength={100}
                    placeholder="npr. Tedenski nakup"
                    required
                    onChange={(event) => {
                      setListName(event.target.value);
                      setSaveMessage(null);
                    }}
                  />
                  <button
                    className="secondary-button"
                    type="submit"
                    disabled={!user || !listName.trim() || selectedItems.length === 0 || saveState === "loading"}
                  >
                    {saveState === "loading" ? "Shranjujem …" : "Shrani seznam"}
                  </button>
                  {!user && <p className="button-help">Za shranjevanje se prijavite zgoraj.</p>}
                  {saveState === "loading" && <p className="sr-only" role="status">Shranjevanje seznama poteka.</p>}
                  {saveMessage && (
                    <p className={saveState === "error" ? "form-error" : "form-success"} role={saveState === "error" ? "alert" : "status"}>
                      {saveMessage}
                    </p>
                  )}
                </form>

                {user && (
                  <section className="saved-card" aria-labelledby="saved-title">
                    <div className="saved-heading">
                      <h2 id="saved-title">Shranjeni seznami</h2>
                      <button type="button" disabled={listsState === "loading"} onClick={() => void loadSavedLists()}>
                        {listsState === "loading" ? "Osvežujem …" : listsState === "error" ? "Poskusi znova" : "Osveži"}
                      </button>
                    </div>
                    {listsState === "loading" ? (
                      <p className="button-help" role="status">Nalaganje seznamov …</p>
                    ) : listsError ? (
                      <p className="form-error" role="alert">{listsError}</p>
                    ) : savedLists.length === 0 ? (
                      <p className="button-help">Nimate še shranjenih seznamov.</p>
                    ) : (
                      <ul>
                        {savedLists.slice(0, 5).map((list) => (
                          <li key={list.id}>
                            <span>{list.name}</span>
                            {list.createdAt && <time dateTime={list.createdAt}>{new Intl.DateTimeFormat("sl-SI", { dateStyle: "medium" }).format(new Date(list.createdAt))}</time>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                )}
              </aside>
            </div>
          )}
        </section>

        {comparison && <ComparisonResults comparison={comparison} headingRef={comparisonHeading} />}
      </main>

      <footer>
        <span><BasketIcon /> Pametna košarica</span>
        <p>Načrtujte nakup. Ohranite drobiž.</p>
      </footer>
    </>
  );
}
