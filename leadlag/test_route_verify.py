#!/usr/bin/env python3
"""test_route_verify.py — Tests unitaires HORS LIGNE (état synthétique,
aucun RPC) pour leadlag/route_verify.py.

Couvre les corrections de l'audit ChatGPT 2026-11-25 :
- #2 : quote par jambe au montant/sens réels ; tolérance < marge cherchée ;
  même-pool exclue ; cycle complet à bloc fixé.
- #11 : grille de tailles $1–$1 000, pas de seuil fixe.
- #12 : gas = coût complet de la transaction exacte (obligatoire, jamais
  de défaut silencieux).
- Régressions : fee en unités 1e-6 (85 = 0,0085 %, pas 0,85 %) ;
  décimales quote (USDC = 6, jamais 18 par défaut) ; fees dynamiques
  lues on-chain au bloc (pas la fee du scan réutilisée).

Lancer depuis polygon/ :  ../.venv/bin/python -m unittest
(ou depuis leadlag/ :  ../.venv/bin/python -m unittest discover -s . -p 'test_*.py')
"""
import math
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'leadlag'))

import cross_venue as cv  # noqa: E402
import route_verify as rv  # noqa: E402
from v3_quote import v3_quote_python  # noqa: E402

Q96 = 2 ** 96
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CBBTC = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
POOL_A = "0x1111111111111111111111111111111111111111"
POOL_B = "0x2222222222222222222222222222222222222222"


def synth_cl_state(pool, mid_quote_per_token, dec_token, dec_quote,
                   fee_bps, liq=4.0e16, tick_spacing=60, factory=None,
                   token0_is_token=True):
    """État CL synthétique : sqrtPriceX96 inversé depuis le mid.
    liq = 4e16 ≈ liquidité réelle d'une pool WETH/USDC profonde
    (1e18 serait trop profonde : le mouvement de prix deviendrait
    inférieur à la résolution float64 pour des montants réalistes)."""
    adj = 10.0 ** (dec_token - dec_quote)
    sqrt_p = math.sqrt(mid_quote_per_token / adj) if token0_is_token \
        else math.sqrt(adj / mid_quote_per_token)
    return {"pool": pool, "pool_type": "cl", "sqrt_x96": int(sqrt_p * Q96),
            "tick": 0, "liq": liq, "fee_bps": fee_bps,
            "fee_source": "pool_fee()", "token0": WETH if token0_is_token else USDC,
            "tick_spacing": tick_spacing,
            "factory": factory or "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"}


class TestMonoTickVsV3Quote(unittest.TestCase):
    """1. Le modèle mono-tick indépendant doit s'accorder avec
    v3_quote_python (implémentation de référence du repo)."""

    def test_agreement_across_fees_and_directions(self):
        for fee_bps in (85, 100, 185, 300, 500, 3000):
            for zfo in (True, False):
                for amount in (1e6, 1e8, 1e9):
                    st = synth_cl_state(POOL_A, 1643.55, 18, 6, fee_bps)
                    out, _, _ = rv.mono_tick_out(amount, st["liq"], st["sqrt_x96"],
                                                 fee_bps, zfo,
                                                 tick_spacing=st["tick_spacing"])
                    q = v3_quote_python(float(amount), float(st["liq"]), st["sqrt_x96"],
                                        fee_bps=fee_bps / 100.0, zero_for_one=zfo)
                    self.assertGreater(out, 0)
                    self.assertAlmostEqual(out, q.amount_out, delta=abs(q.amount_out) * 1e-4,
                                           msg=f"fee={fee_bps} zfo={zfo} amt={amount}")


class TestDecomposeIdentity(unittest.TestCase):
    """2. Idéal − réel == fee + impact (chaque coût compté une seule fois)."""

    def test_identity_both_directions(self):
        """Identité relative : l'erreur absolue en raw est dominée par
        l'arrondi float64 (idéal ~1e16 raw) — on exige une erreur
        RELATIVE < 1e-12, pas absolue."""
        for fee_bps in (85, 500):
            for zfo in (True, False):
                st = synth_cl_state(POOL_A, 1643.55, 18, 6, fee_bps)
                leg = rv.decompose_leg(10_000_000, st["liq"], st["sqrt_x96"],
                                       fee_bps, zero_for_one=zfo,
                                       dec_in=6, dec_out=18,
                                       mid_out_per_in=1.0 / 1643.55,
                                       tick_spacing=60)
                rel = abs(leg["identity_err_raw"]) / max(1.0, abs(leg["ideal_raw"]))
                self.assertLess(rel, 1e-12)
                self.assertGreater(leg["fee_raw"], 0)
                self.assertGreaterEqual(leg["impact_raw"], 0)

    def test_fee_units_regression(self):
        """3. RÉGRESSION : fee 85 = 0,0085 % (85/1e6), PAS 0,85 % (85/1e4).
        L'ancien /10_000 surestimait la fee 100x."""
        st = synth_cl_state(POOL_A, 1643.55, 18, 6, 85)
        leg = rv.decompose_leg(100_000_000, st["liq"], st["sqrt_x96"], 85,
                               zero_for_one=False, dec_in=6, dec_out=18,
                               mid_out_per_in=1.0 / 1643.55, tick_spacing=60)
        # fee attendue : 100 $ × 0,0085 % = 0,0085 $ (en sortie ~0,0085 $)
        self.assertAlmostEqual(leg["fee_raw"] / 1e18 * 1643.55, 0.0085, delta=0.001)
        # et sûrement pas 100x plus (0,85 $) :
        self.assertLess(leg["fee_raw"] / 1e18 * 1643.55, 0.05)


class TestV2Leg(unittest.TestCase):
    """10. Jambe V2 (constant product) : identité + fee 0,30 %."""

    def test_v2_identity_and_fee(self):
        # réserves : 100 WETH / 164 355 USDC (prix 1 643,55)
        leg = rv.decompose_leg_v2(100_000_000, 164_355_000_000, 100_000_000_000_000_000_000,
                                  3000, dec_in=6, dec_out=18,
                                  mid_out_per_in=1.0 / 1643.55)
        rel = abs(leg["identity_err_raw"]) / max(1.0, abs(leg["ideal_raw"]))
        self.assertLess(rel, 1e-12)
        self.assertAlmostEqual(leg["fee_raw"] / 1e18 * 1643.55, 0.30, delta=0.01)
        self.assertGreater(leg["actual_raw"], 0)
        self.assertLess(leg["actual_raw"], leg["ideal_raw"])


class TestVerifyCycleGuards(unittest.TestCase):
    """4–6. Gardes du cycle : même pool, gas obligatoire, identité du net."""

    def _cycle(self, buy_state, sell_state, size=100.0, gas_usd=0.0024,
               dec_t=18, dec_q=6, upq=1.0):
        """upq = USD par unité de QUOTE : 1,0 pour USDC (pas le prix ETH !)."""
        states = {POOL_A: buy_state, POOL_B: sell_state}
        with mock.patch.object(rv, "read_pool_state",
                               side_effect=lambda p, b: states[p]), \
             mock.patch.object(cv, "token_decimals",
                               side_effect=lambda a: {WETH: 18, USDC: 6, CBBTC: 8}[a]):
            return rv.verify_cycle(POOL_A, POOL_B, WETH, USDC, size, upq,
                                   62077712, gas_usd=gas_usd, quoter_guard=False)

    def test_same_pool_rejected(self):
        """4. buy_addr == sell_addr = cycle invalide (audit : la « meilleure
        paire » à $1 000 était la même pool des deux côtés)."""
        st = synth_cl_state(POOL_A, 1643.55, 18, 6, 100)
        with self.assertRaises(ValueError):
            with mock.patch.object(rv, "read_pool_state", return_value=st), \
                 mock.patch.object(cv, "token_decimals", return_value=18):
                rv.verify_cycle(POOL_A, POOL_A, WETH, USDC, 100.0, 1643.55,
                                62077712, gas_usd=0.0024, quoter_guard=False)

    def test_gas_required(self):
        """5. #12 : sans gas_usd explicite, le cycle refuse (jamais de
        $0,0044 figé ni de gas à zéro)."""
        buy = synth_cl_state(POOL_A, 1643.55, 18, 6, 100)
        sell = synth_cl_state(POOL_B, 1643.55, 18, 6, 100)
        with self.assertRaises(RuntimeError):
            self._cycle(buy, sell, gas_usd=None)

    def test_net_identity_offline(self):
        """6. Net décomposé == net direct (écart < 0,001 $) sur état synthétique.
        Écart résiduel connu : les coûts de la jambe 1 sont valorisés au
        mid d'achat, réalisés au mid de vente -> (fee1+imp1) × gap
        (≈ 0,01 $ × 0,216 % = 0,00002 $ ici) ; on tolère 0,001 $."""
        buy = synth_cl_state(POOL_A, 1640.00, 18, 6, 100)
        sell = synth_cl_state(POOL_B, 1643.55, 18, 6, 100)
        r = self._cycle(buy, sell)
        self.assertAlmostEqual(r["net_usd"], r["net_direct_usd"], delta=0.001)
        # gap 0,216 % > fees 0,02 % + gas -> net positif sur l'état synthétique
        self.assertGreater(r["net_direct_usd"], 0)

    def test_dynamic_fee_read_from_state(self):
        """12. La fee utilisée vient de l'ÉTAT au bloc, pas d'une valeur du
        scan : fee 3300 (dynamique Aerodrome) doit donner un net négatif
        là où fee 300 donnerait un positif."""
        buy = synth_cl_state(POOL_A, 1640.00, 18, 6, 100)
        sell_lo = synth_cl_state(POOL_B, 1643.55, 18, 6, 300)
        sell_hi = synth_cl_state(POOL_B, 1643.55, 18, 6, 3300)
        r_lo = self._cycle(buy, sell_lo)
        r_hi = self._cycle(buy, sell_hi)
        self.assertGreater(r_lo["net_direct_usd"], 0)
        self.assertLess(r_hi["net_direct_usd"], 0)
        self.assertEqual(r_hi["fee_sell_bps_onchain"], 3300)


class TestSizeGrid(unittest.TestCase):
    """7. Grille $1–$1 000 : le net décroît avec la taille quand le gap est
    sous le breakeven ; la taille optimale est la plus petite."""

    def test_net_decreases_with_size(self):
        """Gap 0,0091 % < fees 0,02 % : le net est négatif à toutes les
        tailles et décroît (le gas fixe pèse plus à petite taille, mais
        l'impact croît plus vite que le brut — l'optimum reste 1 $)."""
        buy = synth_cl_state(POOL_A, 1643.40, 18, 6, 100)
        sell = synth_cl_state(POOL_B, 1643.55, 18, 6, 100)
        nets = []
        for size in (1, 5, 10, 25, 50, 100, 250, 500, 1000):
            states = {POOL_A: buy, POOL_B: sell}
            with mock.patch.object(rv, "read_pool_state",
                                   side_effect=lambda p, b: states[p]), \
                 mock.patch.object(cv, "token_decimals",
                                   side_effect=lambda a: {WETH: 18, USDC: 6}[a]):
                r = rv.verify_cycle(POOL_A, POOL_B, WETH, USDC, size, 1.0,
                                    62077712, gas_usd=0.0024, quoter_guard=False)
            nets.append(r["net_direct_usd"])
            self.assertGreater(r["net_direct_usd"], -size)  # jamais pire que -100 %
        self.assertEqual(nets, sorted(nets, reverse=True))
        self.assertEqual(max(nets), nets[0])  # optimum = 1 $


class TestDecimalsRegression(unittest.TestCase):
    """8. RÉGRESSION décimales : USDC lu à 18 décimales (défaut silencieux)
    donnait des nets ≈ −100 $ ; à 6 décimales le net est sain (≈ −0,02 $)."""

    def test_usdc_6_decimals_sane(self):
        buy = synth_cl_state(POOL_A, 1643.40, 18, 6, 100)
        sell = synth_cl_state(POOL_B, 1643.55, 18, 6, 100)
        states = {POOL_A: buy, POOL_B: sell}
        with mock.patch.object(rv, "read_pool_state",
                               side_effect=lambda p, b: states[p]), \
             mock.patch.object(cv, "token_decimals",
                               side_effect=lambda a: {WETH: 18, USDC: 6}[a]):
            r = rv.verify_cycle(POOL_A, POOL_B, WETH, USDC, 100.0, 1.0,
                                62077712, gas_usd=0.0024, quoter_guard=False)
        self.assertGreater(r["net_direct_usd"], -1.0)
        self.assertLess(r["net_direct_usd"], 0)

    def test_usdc_18_decimals_garbage(self):
        buy = synth_cl_state(POOL_A, 1643.40, 18, 6, 100)
        sell = synth_cl_state(POOL_B, 1643.55, 18, 6, 100)
        states = {POOL_A: buy, POOL_B: sell}
        with mock.patch.object(rv, "read_pool_state",
                               side_effect=lambda p, b: states[p]), \
             mock.patch.object(cv, "token_decimals",
                               side_effect=lambda a: {WETH: 18, USDC: 18}[a]):
            r = rv.verify_cycle(POOL_A, POOL_B, WETH, USDC, 100.0, 1.0,
                                62077712, gas_usd=0.0024, quoter_guard=False)
        self.assertLess(r["net_direct_usd"], -50.0)  # signature du bug


class TestQuoterTolerance(unittest.TestCase):
    """9. Tolérance quoter = max(0,5 bp, 1 unité de sortie) — jamais 2 %."""

    def test_quantization_floor(self):
        self.assertAlmostEqual(rv.quoter_tol_pct(1703), 100.0 / 1703, delta=1e-9)
        self.assertAlmostEqual(rv.quoter_tol_pct(170382), 0.005, delta=1e-12)
        self.assertAlmostEqual(rv.quoter_tol_pct(0), 0.005, delta=1e-12)
        self.assertLess(rv.QUOTER_TOL_PCT, 0.01)  # 0,5 bp, pas 200 bp


class TestTokenDecimalsStrict(unittest.TestCase):
    """11. token_decimals ne doit JAMAIS tomber à 18 par défaut sur échec RPC."""

    def test_raises_on_rpc_failure(self):
        cv._DECIMALS_CACHE.pop(USDC.lower(), None)
        with mock.patch.object(cv, "eth_call", side_effect=RuntimeError("RPC down")):
            with self.assertRaises(RuntimeError):
                cv.token_decimals(USDC)


if __name__ == "__main__":
    unittest.main()
