"use client";

import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { api, getErrorMessage, type User } from "@/lib/api";

type AuthPanelProps = {
  authLoading: boolean;
  authError: string | null;
  user: User | null;
  onAuthenticated: (user: User) => void;
  onLogout: () => Promise<void>;
  onRetrySession: () => void;
};

export function AuthPanel({
  authLoading,
  authError,
  user,
  onAuthenticated,
  onLogout,
  onRetrySession,
}: AuthPanelProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const emailId = useId();
  const passwordId = useId();
  const titleId = useId();

  function closePanel(restoreFocus = true) {
    setOpen(false);
    setMode("login");
    setEmail("");
    setPassword("");
    setError(null);
    if (restoreFocus) queueMicrotask(() => triggerRef.current?.focus());
  }

  useEffect(() => {
    if (!open) return;
    emailRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        setMode("login");
        setEmail("");
        setPassword("");
        setError(null);
        queueMicrotask(() => triggerRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, mode]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);

    try {
      if (mode === "login") await api.login(email.trim(), password);
      else await api.register(email.trim(), password);
      const currentUser = await api.me();
      onAuthenticated(currentUser);
      setEmail("");
      setPassword("");
      setOpen(false);
    } catch (reason) {
      setError(getErrorMessage(reason));
      setPassword("");
    } finally {
      setPending(false);
    }
  }

  if (authLoading) {
    return <p className="auth-check" role="status">Preverjanje prijave …</p>;
  }

  if (authError && !user) {
    return (
      <div className="auth-session-error" role="alert">
        <span>Prijave ni bilo mogoče preveriti. {authError}</span>
        <button className="text-button" type="button" onClick={onRetrySession}>Poskusi znova</button>
      </div>
    );
  }

  if (user) {
    return (
      <div>
        <div className="user-menu">
          <span className="user-avatar" aria-hidden="true">{user.email.slice(0, 1).toUpperCase()}</span>
          <span className="user-email" title={user.email}>{user.email}</span>
          <button
            className="text-button"
            type="button"
            disabled={logoutPending}
            onClick={async () => {
              if (logoutPending) return;
              setLogoutPending(true);
              setError(null);
              try {
                await onLogout();
              } catch (reason) {
                setError(getErrorMessage(reason));
              } finally {
                setLogoutPending(false);
              }
            }}
          >
            {logoutPending ? "Odjavljanje …" : "Odjava"}
          </button>
        </div>
        {error && <p className="auth-menu-error" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <div className="auth-wrap">
      <button
        ref={triggerRef}
        className="auth-trigger"
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="auth-form-panel"
        onClick={() => {
          if (open) closePanel();
          else {
            setOpen(true);
            setError(null);
          }
        }}
      >
        Prijava <span aria-hidden="true">↗</span>
      </button>

      {open && (
        <div
          className="auth-modal-backdrop"
          onMouseDown={() => closePanel()}
        >
          <div
            ref={panelRef}
            className="auth-popover"
            id="auth-form-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="auth-tabs" aria-label="Vrsta računa">
              <button
                type="button"
                aria-pressed={mode === "login"}
                onClick={() => {
                  setMode("login");
                  setPassword("");
                  setError(null);
                }}
              >
                Prijava
              </button>
              <button
                type="button"
                aria-pressed={mode === "register"}
                onClick={() => {
                  setMode("register");
                  setPassword("");
                  setError(null);
                }}
              >
                Nov račun
              </button>
            </div>
            <form onSubmit={handleSubmit}>
              <h2 id={titleId}>{mode === "login" ? "Dobrodošli nazaj" : "Ustvarite račun"}</h2>
              <p className="auth-hint">
                {mode === "login"
                  ? "Prijavite se, da lahko shranite seznam."
                  : "Račun potrebujete samo za shranjevanje seznamov."}
              </p>
              <label htmlFor={emailId}>E-poštni naslov</label>
              <input
                ref={emailRef}
                id={emailId}
                type="email"
                autoComplete="email"
                value={email}
                maxLength={254}
                required
                onChange={(event) => setEmail(event.target.value)}
              />
              <label htmlFor={passwordId}>Geslo</label>
              <input
                id={passwordId}
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                minLength={mode === "register" ? 12 : 1}
                maxLength={128}
                required
                onChange={(event) => setPassword(event.target.value)}
              />
              {mode === "register" && <p className="auth-hint">Uporabite najmanj 12 znakov.</p>}
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="primary-button auth-submit" type="submit" disabled={pending}>
                {pending ? "Pošiljanje …" : mode === "login" ? "Prijavi me" : "Ustvari račun"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
