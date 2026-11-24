#!/usr/bin/env python3
"""
watchlist.py — Watchlist persistante des tokens meme Polygon (v4.1).

Enregistre CHAQUE token vu (GeckoTerminal new pools + DexScreener
token-profiles latest) dans watchlist.json, et le RE-VÉRIFIE à chaque
run : un token liste souvent sa 2e venue des heures/jours après son
launch — le scan one-shot la rate, la watchlist la capte.

Tiers (fenêtres) :
  - "exec"  : liq 5 000–100 000 $, âge < 72 h → éligible à l'exécution
              (si 2 venues + GoPlus OK + spread ≥ 3 % + net ≥ 3 $ après gas).
  - "watch" : liq 1 000–500 000 $, âge < 7 jours → SUIVI UNIQUEMENT.
              JAMAIS exécuté, même avec 2 venues : il sert à détecter
              l'apparition d'une 2e venue et à promouvoir le token en
              "exec" quand il rentre dans la fenêtre d'exécution.
  - "none"  : hors des deux fenêtres (poussière < 1 k $, baleine > 500 k $,
              ou âge > 7 jours) → gardé en historique, non re-vérifié.

Structure watchlist.json :
  {
    "version": 1,
    "updated": "<ISO>",
    "tokens": {
      "<adresse minuscule>": {
        "address": ..., "name": ...,
        "first_seen": "<ISO>", "last_seen": "<ISO>",
        "venues": {"quickswap": [{"pair": ..., "liq_usd": ...}], ...},
        "dexs": ["quickswap", "uniswap"],
        "max_liq_usd_seen": 12345.6,
        "max_age_h_seen": 1.2,   # âge de la PLUS ANCIENNE paire vue
        "tier": "watch" | "exec" | "none",
        "goplus": {"ok": true/false/null, "note": "...", "checked": "<ISO>"},
        "second_venue_first_seen": "<ISO>" | null,
        "promotions": ["watch->exec ..."],
        "source": "geckoterminal" | "dexscreener-profiles"
      }
    }
  }

Simulation seulement — aucune donnée ici ne déclenche un broadcast.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Fenêtre d'EXÉCUTION (inchangée v4.0 — mêmes gardes que scanner_polygon.py)
EXEC_MIN_LIQ_USD = 5_000.0
EXEC_MAX_LIQ_USD = 100_000.0
EXEC_MAX_AGE_H = 72.0
# Fenêtre de SURVEILLANCE (élargie v4.1 — suivi sans exécution)
WATCH_MIN_LIQ_USD = 1_000.0
WATCH_MAX_LIQ_USD = 500_000.0
WATCH_MAX_AGE_H = 7 * 24.0  # 168 h

DEFAULT_STORE = Path(__file__).parent / "watchlist.json"


def normalize_dex(dex_id: str) -> str:
    """Unifie les noms de DEX entre sources — sinon le MÊME DEX compte
    pour 2 venues (faux positif) :
      GeckoTerminal : 'uniswap_v3_polygon_pos' / 'uniswap-v4-polygon'
      DexScreener   : 'uniswap' (= V3), 'quickswap', 'sushiswap', …
    'uniswap_v3_polygon_pos' → 'uniswap' ; 'uniswap-v4-polygon' →
    'uniswap-v4' (V4 distincte, DexScreener ne l'indexe pas encore).
    Les dexId inconnus (parfois une adresse de contrat chez DexScreener)
    sont conservés tels quels, en minuscules."""
    d = (dex_id or "unknown").strip().lower()
    d = (d.replace("_polygon_pos", "").replace("-polygon-pos", "")
          .replace("-polygon", "").replace("_polygon", ""))
    d = d.replace("uniswap_v3", "uniswap").replace("uniswap-v3", "uniswap")
    return d or "unknown"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_tier(liq_usd: float, age_h: float) -> str:
    """'exec' | 'watch' | 'none' selon liq + âge. 'watch' n'exécute JAMAIS."""
    if EXEC_MIN_LIQ_USD <= liq_usd <= EXEC_MAX_LIQ_USD and age_h <= EXEC_MAX_AGE_H:
        return "exec"
    if WATCH_MIN_LIQ_USD <= liq_usd <= WATCH_MAX_LIQ_USD and age_h <= WATCH_MAX_AGE_H:
        return "watch"
    return "none"


class Watchlist:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_STORE
        self.tokens: dict = {}
        self.updated: str | None = None
        self.load()

    # -- persistance ------------------------------------------------------
    def load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except Exception:  # noqa: BLE001
            return
        self.tokens = data.get("tokens", {}) or {}
        self.updated = data.get("updated")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "updated": utcnow_iso(), "tokens": self.tokens}
        self.path.write_text(json.dumps(data, indent=2))

    # -- mise à jour ------------------------------------------------------
    def upsert(self, address: str, name: str | None = None,
               venues: dict | None = None, liq_usd: float | None = None,
               age_h: float | None = None,
               source: str | None = None) -> dict:
        """Ajoute ou met à jour un token. Retourne l'entrée + la clé
        '_new_second_venue' (True si une 2e venue vient d'apparaître)."""
        addr = address.lower()
        now = utcnow_iso()
        entry = self.tokens.get(addr)
        if entry is None:
            entry = {"address": addr, "name": name, "first_seen": now,
                     "last_seen": now, "venues": {}, "dexs": [],
                     "max_liq_usd_seen": 0.0, "max_age_h_seen": None,
                     "tier": "none", "goplus": {"ok": None, "note": None,
                                                "checked": None},
                     "second_venue_first_seen": None, "promotions": [],
                     "source": source}
            self.tokens[addr] = entry
        # Compat : anciens stores utilisaient min_age_h_seen.
        if entry.get("max_age_h_seen") is None and \
                entry.get("min_age_h_seen") is not None:
            entry["max_age_h_seen"] = entry.pop("min_age_h_seen")
        old_dexs = set(entry.get("dexs") or [])
        entry["last_seen"] = now
        if name:
            entry["name"] = name
        if source and not entry.get("source"):
            entry["source"] = source
        if venues:
            # Fusion : on garde toutes les paires vues par DEX.
            # Les clés sont normalisées (normalize_dex) : le même DEX vu
            # via GeckoTerminal puis DexScreener ne compte qu'UNE venue.
            # Une même adresse de paire vue sous deux labels de DEX
            # (ex : 'quickswap-v4' Gecko vs 'quickswap' DexScreener)
            # ne compte qu'UNE venue : on déduplique par adresse.
            merged = entry.setdefault("venues", {})
            known_pairs = {str(p.get("pair")).lower()
                           for pairs in merged.values() for p in pairs
                           if p.get("pair")}
            for dex, pairs in venues.items():
                dex = normalize_dex(dex)
                known = {str(p.get("pair")).lower()
                         for p in merged.get(dex, []) if p.get("pair")}
                merged.setdefault(dex, [])
                for p in pairs:
                    pair_addr = str(p.get("pair") or "").lower()
                    if not pair_addr or pair_addr in known_pairs:
                        continue
                    merged[dex].append({**p, "pair": pair_addr})
                    known.add(pair_addr)
                    known_pairs.add(pair_addr)
            # Supprime les DEX devenus vides (toutes leurs paires étaient
            # déjà connues sous un autre label).
            entry["venues"] = {d: ps for d, ps in merged.items() if ps}
            entry["dexs"] = sorted(entry["venues"].keys())
        if liq_usd is not None:
            entry["max_liq_usd_seen"] = max(entry.get("max_liq_usd_seen") or 0.0,
                                            float(liq_usd))
        if age_h is not None:
            prev = entry.get("max_age_h_seen")
            entry["max_age_h_seen"] = age_h if prev is None else max(prev, age_h)
        # Tier : recalculé sur les MEILLEURES données connues —
        # liquidité max vue, âge de la PLUS ANCIENNE paire vue.
        # Un token promu par erreur (nouvelle pool d'un vieux token)
        # est RÉTROGRADÉ quand DexScreener révèle son vrai âge : la
        # fenêtre meme porte sur le lancement du token, pas d'une pool.
        # La liquidité étant un max monotone, il n'y a pas de
        # rétrogradation par fluctuation de liquidité.
        old_tier = entry.get("tier", "none")
        max_liq = entry.get("max_liq_usd_seen") or 0.0
        max_age = entry.get("max_age_h_seen")
        if max_age is not None:
            new_tier = classify_tier(max_liq, max_age)
            if new_tier != old_tier:
                entry["tier"] = new_tier
                entry["promotions"].append(
                    f"{old_tier}->{new_tier} {now}")
        # Détection 2e venue : 0/1 dex avant, ≥2 maintenant.
        new_dexs = set(entry.get("dexs") or [])
        new_second = len(old_dexs) < 2 and len(new_dexs) >= 2
        if new_second and not entry.get("second_venue_first_seen"):
            entry["second_venue_first_seen"] = now
        entry["_new_second_venue"] = new_second
        return entry

    def set_goplus(self, address: str, ok: bool, note: str):
        entry = self.tokens.get(address.lower())
        if entry is None:
            return
        entry["goplus"] = {"ok": ok, "note": note, "checked": utcnow_iso()}

    # -- requêtes ---------------------------------------------------------
    def tokens_to_recheck(self, max_age_days: float = 7.0) -> list:
        """Tokens à re-vérifier : tier exec/watch, vus il y a < 7 jours.
        Les 'none' (poussière/baleine/vieux) ne sont pas re-vérifiés."""
        now = datetime.now(timezone.utc)
        out = []
        for addr, e in self.tokens.items():
            if e.get("tier") not in ("exec", "watch"):
                continue
            try:
                last = datetime.fromisoformat(
                    e["last_seen"].replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                continue
            if (now - last).total_seconds() <= max_age_days * 86400:
                out.append(addr)
        return out

    def two_venue_tokens(self, tier: str | None = None) -> list:
        out = []
        for addr, e in self.tokens.items():
            if len(e.get("dexs") or []) >= 2:
                if tier is None or e.get("tier") == tier:
                    out.append(addr)
        return out

    def stats(self) -> dict:
        tiers = {"exec": 0, "watch": 0, "none": 0}
        for e in self.tokens.values():
            tiers[e.get("tier", "none")] = tiers.get(e.get("tier", "none"), 0) + 1
        return {"total_tokens": len(self.tokens),
                "tier_exec": tiers["exec"], "tier_watch": tiers["watch"],
                "tier_none": tiers["none"],
                "two_venue_total": len(self.two_venue_tokens()),
                "two_venue_exec": len(self.two_venue_tokens("exec")),
                "two_venue_watch": len(self.two_venue_tokens("watch")),
                "updated": self.updated}
