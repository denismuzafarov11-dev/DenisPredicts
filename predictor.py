import io
import sys
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import matplotlib.pyplot as plt
from scipy.stats import poisson, nbinom
from scipy.optimize import minimize_scalar
from tabulate import tabulate


class FastEloSystem:
    """Динамический рейтинг Эло с учетом домашнего бонуса и разницы мячей."""
    def __init__(self, base: float = 1500.0, k: float = 24.0, hfa: float = 65.0):
        self.base = base
        self.k = k
        self.hfa = hfa
        self.ratings = {}

    def get(self, team: str) -> float:
        return self.ratings.get(team, self.base)

    def fit(self, df: pd.DataFrame):
        for _, r in df.iterrows():
            h, a = r["HomeTeam"], r["AwayTeam"]
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
            rh, ra = self.get(h), self.get(a)
            exp_h = 1.0 / (1.0 + 10.0 ** ((ra - (rh + self.hfa)) / 400.0))
            s_h = 1.0 if hg > ag else (0.0 if hg < ag else 0.5)
            diff = abs(hg - ag)
            mov = np.log(diff + 1.0) * (2.2 / ((abs(rh - ra) * 0.001) + 2.2)) if diff > 0 else 1.0
            delta = self.k * mov * (s_h - exp_h)
            self.ratings[h] = rh + delta
            self.ratings[a] = ra - delta

    def multipliers(self, home: str, away: str) -> tuple[float, float]:
        diff = (self.get(home) + self.hfa) - self.get(away)
        return float(np.clip(1.0 + diff / 2500.0, 0.82, 1.22)), float(np.clip(1.0 - diff / 2500.0, 0.82, 1.22))


class MasterPredictorEngine:
    """Полный математический комплекс для прогнозирования матчей."""
    def __init__(self, train_df: pd.DataFrame, half_life: float = 115.0):
        self.df = self._apply_time_decay(train_df, half_life)
        self.elo = FastEloSystem()
        self.elo.fit(self.df)
        self.goals_stats, self.g_avg_h, self.g_avg_a = self._fit_goals()
        self.rho = self._optimize_rho()
        self.corn_stats, self.c_avg_h, self.c_avg_a, self.c_alpha = self._fit_counts("HC", "AC", "HS", "AS")
        self.card_stats, self.k_avg_h, self.k_avg_a, self.k_alpha = self._fit_counts("HY", "AY", "HF", "AF")
        self.ref_factors = self._fit_referees()

    @staticmethod
    def _apply_time_decay(df: pd.DataFrame, half_life: float) -> pd.DataFrame:
        df = df.copy()
        max_dt = df["ParsedDate"].max()
        days = (max_dt - df["ParsedDate"]).dt.days.clip(lower=0)
        df["weight"] = np.exp(-(np.log(2) / half_life) * days)
        return df

    def _fit_goals(self):
        df = self.df
        if {"HS", "AS", "HST", "AST"}.issubset(df.columns):
            sot_h = df["FTHG"].sum() / max(1.0, df["HST"].dropna().sum())
            sot_a = df["FTAG"].sum() / max(1.0, df["AST"].dropna().sum())
            px_h = 0.70 * df["FTHG"] + 0.30 * (df["HST"].fillna(df["FTHG"]) * sot_h)
            px_a = 0.70 * df["FTAG"] + 0.30 * (df["AST"].fillna(df["FTAG"]) * sot_a)
        else:
            px_h, px_a = df["FTHG"], df["FTAG"]

        df["wh"] = px_h * df["weight"]
        df["wa"] = px_a * df["weight"]
        tw = df["weight"].sum()
        avg_h = max(0.2, float(df["wh"].sum() / tw))
        avg_a = max(0.2, float(df["wa"].sum() / tw))

        hg = df.groupby("HomeTeam").agg(wg=("weight", "sum"), wf=("wh", "sum"), wag=("wa", "sum"))
        ag = df.groupby("AwayTeam").agg(wg=("weight", "sum"), wf=("wa", "sum"), wag=("wh", "sum"))
        st = hg.join(ag, suffixes=("_h", "_a"), how="outer").fillna(0)

        st["att_h"] = (st["wf_h"] / np.maximum(st["wg_h"], 1e-4)) / avg_h
        st["def_h"] = (st["wag_h"] / np.maximum(st["wg_h"], 1e-4)) / avg_a
        st["att_a"] = (st["wf_a"] / np.maximum(st["wg_a"], 1e-4)) / avg_a
        st["def_a"] = (st["wag_a"] / np.maximum(st["wg_a"], 1e-4)) / avg_h
        return st.replace([np.inf, -np.inf], 1.0).fillna(1.0), avg_h, avg_a

    def _optimize_rho(self) -> float:
        records = []
        for _, r in self.df.iterrows():
            h, a = r["HomeTeam"], r["AwayTeam"]
            if h in self.goals_stats.index and a in self.goals_stats.index:
                lh = self.goals_stats.loc[h, "att_h"] * self.goals_stats.loc[a, "def_a"] * self.g_avg_h
                la = self.goals_stats.loc[a, "att_a"] * self.goals_stats.loc[h, "def_h"] * self.g_avg_a
                records.append((int(r["FTHG"]), int(r["FTAG"]), lh, la, float(r["weight"])))
        if not records:
            return -0.11

        def neg_ll(rho_val: float) -> float:
            ll = 0.0
            for x, y, lam, mu, w in records:
                t = 1.0
                if x == 0 and y == 0: t = 1.0 - lam * mu * rho_val
                elif x == 0 and y == 1: t = 1.0 + lam * rho_val
                elif x == 1 and y == 0: t = 1.0 + mu * rho_val
                elif x == 1 and y == 1: t = 1.0 - rho_val
                if t <= 1e-5: return 1e9
                ll += w * np.log(t)
            return -ll

        res = minimize_scalar(neg_ll, bounds=(-0.22, 0.05), method="bounded")
        return float(res.x) if res.success else -0.11

    def _fit_counts(self, h_col: str, a_col: str, aux_h: str, aux_a: str):
        sub = self.df.dropna(subset=[h_col, a_col]).copy()
        if sub.empty: return pd.DataFrame(), 1.0, 1.0, 0.0
        if aux_h in sub.columns and aux_a in sub.columns:
            r_h = sub[h_col].sum() / max(1.0, sub[aux_h].dropna().sum())
            r_a = sub[a_col].sum() / max(1.0, sub[aux_a].dropna().sum())
            eh = 0.75 * sub[h_col] + 0.25 * (sub[aux_h].fillna(0) * r_h)
            ea = 0.75 * sub[a_col] + 0.25 * (sub[aux_a].fillna(0) * r_a)
        else:
            eh, ea = sub[h_col], sub[a_col]

        sub["wh"] = eh * sub["weight"]
        sub["wa"] = ea * sub["weight"]
        tw = sub["weight"].sum()
        avg_h = max(0.2, float(sub["wh"].sum() / tw))
        avg_a = max(0.2, float(sub["wa"].sum() / tw))

        tot = sub[h_col] + sub[a_col]
        m_tot, v_tot = float(tot.mean()), float(tot.var())
        alpha = (v_tot - m_tot) / (m_tot ** 2) if v_tot > m_tot * 1.05 else 0.0

        hg = sub.groupby("HomeTeam").agg(wg=("weight", "sum"), wf=("wh", "sum"), wag=("wa", "sum"))
        ag = sub.groupby("AwayTeam").agg(wg=("weight", "sum"), wf=("wa", "sum"), wag=("wh", "sum"))
        st = hg.join(ag, suffixes=("_h", "_a"), how="outer").fillna(0)
        st["att_h"] = (st["wf_h"] / np.maximum(st["wg_h"], 1e-4)) / avg_h
        st["def_h"] = (st["wag_h"] / np.maximum(st["wg_h"], 1e-4)) / avg_a
        st["att_a"] = (st["wf_a"] / np.maximum(st["wg_a"], 1e-4)) / avg_a
        st["def_a"] = (st["wag_a"] / np.maximum(st["wg_a"], 1e-4)) / avg_h
        return st.replace([np.inf, -np.inf], 1.0).fillna(1.0), avg_h, avg_a, alpha

    def _fit_referees(self) -> dict:
        if not {"Referee", "HY", "AY"}.issubset(self.df.columns): return {}
        sub = self.df.dropna(subset=["Referee", "HY", "AY"]).copy()
        if sub.empty: return {}
        sub["yc"] = sub["HY"] + sub["AY"]
        sub["wyc"] = sub["yc"] * sub["weight"]
        l_avg = max(0.5, float(sub["wyc"].sum() / sub["weight"].sum()))
        grp = sub.groupby("Referee").agg(w=("weight", "sum"), wyc=("wyc", "sum"))
        grp["avg"] = grp["wyc"] / np.maximum(grp["w"], 1e-5)
        grp["factor"] = ((grp["w"] * grp["avg"]) + (5.0 * l_avg)) / ((grp["w"] + 5.0) * l_avg)
        return grp["factor"].to_dict()

    @staticmethod
    def _nbinom_over(mu: float, alpha: float, line: float) -> float:
        k = int(np.floor(line))
        if alpha > 0.005:
            var = mu + alpha * (mu ** 2)
            p = mu / var
            n = (mu ** 2) / (var - mu)
            return 1.0 - float(nbinom.cdf(k, n, p))
        return 1.0 - float(poisson.cdf(k, mu))

    def predict_match(self, home: str, away: str, referee: str = None) -> dict:
        if home in self.goals_stats.index and away in self.goals_stats.index:
            lh = self.goals_stats.loc[home, "att_h"] * self.goals_stats.loc[away, "def_a"] * self.g_avg_h
            la = self.goals_stats.loc[away, "att_a"] * self.goals_stats.loc[home, "def_h"] * self.g_avg_a
        else:
            lh, la = self.g_avg_h, self.g_avg_a

        eh, ea = self.elo.multipliers(home, away)
        lam = max(0.2, float(lh * (0.85 + 0.15 * eh)))
        mu = max(0.2, float(la * (0.85 + 0.15 * ea)))

        hp = [poisson.pmf(i, lam) for i in range(7)]
        ap = [poisson.pmf(j, mu) for j in range(7)]
        mat = np.outer(hp, ap)

        r = self.rho
        mat[0, 0] *= max(0.1, 1.0 - lam * mu * r)
        mat[0, 1] *= max(0.1, 1.0 + lam * r)
        mat[1, 0] *= max(0.1, 1.0 + mu * r)
        mat[1, 1] *= max(0.1, 1.0 - r)
        mat /= np.sum(mat)

        p_h = float(np.sum(np.tril(mat, -1)))
        p_d = float(np.sum(np.diag(mat)))
        p_a = float(np.sum(np.triu(mat, 1)))
        s_grid = np.fromfunction(lambda i, j: i + j, (7, 7))
        p_o25 = float(np.sum(mat[s_grid > 2.5]))
        p_btts = float(np.sum(mat[1:, 1:]))

        scores = [((i, j), mat[i, j]) for i in range(7) for j in range(7)]
        scores.sort(key=lambda x: x[1], reverse=True)

        if not self.corn_stats.empty and home in self.corn_stats.index and away in self.corn_stats.index:
            ch = self.corn_stats.loc[home, "att_h"] * self.corn_stats.loc[away, "def_a"] * self.c_avg_h
            ca = self.corn_stats.loc[away, "att_a"] * self.corn_stats.loc[home, "def_h"] * self.c_avg_a
        else:
            ch, ca = self.c_avg_h, self.c_avg_a
        c_tot = max(1.0, float(ch + ca))

        ref_mult = self.ref_factors.get(referee, 1.0)
        if not self.card_stats.empty and home in self.card_stats.index and away in self.card_stats.index:
            kh = self.card_stats.loc[home, "att_h"] * self.card_stats.loc[away, "def_a"] * self.k_avg_h * ref_mult
            ka = self.card_stats.loc[away, "att_a"] * self.card_stats.loc[home, "def_h"] * self.k_avg_a * ref_mult
        else:
            kh, ka = self.k_avg_h * ref_mult, self.k_avg_a * ref_mult
        k_tot = max(0.5, float(kh + ka))

        return {
            "xg_h": lam, "xg_a": mu,
            "1x2": (p_h, p_d, p_a),
            "over_25": p_o25, "under_25": 1.0 - p_o25, "btts": p_btts,
            "top_scores": scores[:3],
            "corn_exp": c_tot, "corn_o95": self._nbinom_over(c_tot, self.c_alpha, 9.5),
            "card_exp": k_tot, "card_o45": self._nbinom_over(k_tot, self.k_alpha, 4.5),
        }


def download_data(div_code: str = "E0"):
    now = datetime.now()
    yr = now.year % 100
    seasons = [f"{yr-3:02d}{yr-2:02d}", f"{yr-2:02d}{yr-1:02d}", f"{yr-1:02d}{yr:02d}"] if now.month < 7 else [f"{yr-2:02d}{yr-1:02d}", f"{yr-1:02d}{yr:02d}", f"{yr:02d}{yr+1:02d}"]
    headers = {"User-Agent": "Mozilla/5.0"}
    frames = []
    for s in seasons:
        url = f"https://www.football-data.co.uk/mmz4281/{s}/{div_code}.csv"
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200 and len(r.content) > 400:
                df = pd.read_csv(io.StringIO(r.text), on_bad_lines="skip")
                if {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}.issubset(df.columns):
                    frames.append(df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]))
        except Exception:
            pass
    if not frames: raise RuntimeError("Ошибка загрузки данных лиги.")
    full = pd.concat(frames, ignore_index=True)
    full = full.copy()
    full["ParsedDate"] = pd.to_datetime(full["Date"], dayfirst=True, errors="coerce")
    full = full.dropna(subset=["ParsedDate"]).sort_values("ParsedDate").reset_index(drop=True)

    fix = pd.DataFrame()
    try:
        rf = requests.get("https://www.football-data.co.uk/fixtures.csv", headers=headers, timeout=10)
        if rf.status_code == 200 and len(rf.content) > 100:
            all_f = pd.read_csv(io.StringIO(rf.text), on_bad_lines="skip")
            if "Div" in all_f.columns: fix = all_f[all_f["Div"] == div_code].copy()
    except Exception:
        pass
    return full, fix


def main():
    print("=" * 95)
    print("  ULTIMATE QUANTITATIVE FOOTBALL SUITE: PREDICTIONS + BACKTEST + EXCEL + CHART  ")
    print("=" * 95)

    leagues = {
        "1": ("Англия: Премьер-лига (EPL)", "E0"),
        "2": ("Испания: Ла Лига", "SP1"),
        "3": ("Италия: Серия А", "I1"),
        "4": ("Германия: Бундеслига", "D1"),
        "5": ("Франция: Лига 1", "F1"),
    }
    for k, (name, _) in leagues.items(): print(f"  [{k}] {name}")
    sel = input("\nВыберите номер лиги [по умолчанию 1]: ").strip()
    l_title, div_code = leagues.get(sel, leagues["1"])

    print(f"\n[*] Загрузка архивов и запуск самообучающегося движка для {l_title}...")
    history_df, fixtures_df = download_data(div_code)

    target_df = fixtures_df if not fixtures_df.empty else history_df.tail(10)
    engine = MasterPredictorEngine(history_df)

    # Генерация прогнозов
    rows = []
    for _, r in target_df.iterrows():
        h, a = r["HomeTeam"], r["AwayTeam"]
        p = engine.predict_match(h, a, referee=r.get("Referee", None))
        ph, pd_p, pa = p["1x2"]
        scores_str = ", ".join([f"{s[0]}:{s[1]} ({pr*100:.1f}%)" for s, pr in p["top_scores"]])

        rows.append({
            "Date": r.get("Date", ""),
            "HomeTeam": h, "AwayTeam": a,
            "xG_Home": round(p["xg_h"], 2), "xG_Away": round(p["xg_a"], 2),
            "Prob_1_%": round(ph * 100, 1), "Prob_X_%": round(pd_p * 100, 1), "Prob_2_%": round(pa * 100, 1),
            "Over_2.5_%": round(p["over_25"] * 100, 1), "BTTS_%": round(p["btts"] * 100, 1),
            "Top_Scores": scores_str,
            "Exp_Corners": round(p["corn_exp"], 2), "Corners_O9.5_%": round(p["corn_o95"] * 100, 1),
            "Exp_Cards": round(p["card_exp"], 2), "Cards_O4.5_%": round(p["card_o45"] * 100, 1),
        })

    pred_df = pd.DataFrame(rows)

    # Простой бэктест на последних 50 матчах для генерации Equity Curve
    print("[*] Выполнение симуляции бэктеста на последних 50 матчах...")
    test_slice = history_df.tail(50).reset_index(drop=True)
    equity_log = [{"Bet_No": 0, "Kelly_Bank": 100.0, "Drawdown_%": 0.0}]
    bank = 100.0
    peak = 100.0

    for i in range(len(test_slice) - 10):
        sub_train = history_df.iloc[:len(history_df) - 50 + i]
        sub_engine = MasterPredictorEngine(sub_train)
        match = test_slice.iloc[i]
        hp = sub_engine.predict_match(match["HomeTeam"], match["AwayTeam"], match.get("Referee"))

        hg, ag = int(match["FTHG"]), int(match["FTAG"])
        actual_o25 = (hg + ag) > 2.5
        pred_o25 = hp["over_25"] >= 0.5

        odd = float(match.get("B365>2.5", 1.95) or 1.95)
        pr = hp["over_25"]
        won = (pred_o25 == actual_o25)

        b = odd - 1.0
        k_frac = min(0.05, max(0.0, ((b * pr - (1.0 - pr)) / b) * 0.20)) if odd > 1.0 else 0.01
        stake = bank * k_frac
        bank += stake * b if won else -stake
        peak = max(peak, bank)
        dd = ((peak - bank) / peak) * 100.0

        equity_log.append({
            "Bet_No": i + 1,
            "Kelly_Bank": round(bank, 2),
            "Drawdown_%": round(dd, 2)
        })

    eq_df = pd.DataFrame(equity_log)

    # Сохранение графика
    plt.figure(figsize=(10, 4))
    plt.plot(eq_df["Bet_No"], eq_df["Kelly_Bank"], color="#1971C2", linewidth=2, label="Kelly Strategy")
    plt.axhline(100, color="gray", linestyle=":")
    plt.title(f"Equity Curve — {l_title}")
    plt.xlabel("Bets")
    plt.ylabel("Bankroll")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig("equity_curve.png", dpi=150)
    plt.close()
    print("[+] График сохранен в equity_curve.png")

    # Сохранение Excel
    with pd.ExcelWriter("betting_analytics_report.xlsx", engine="openpyxl") as writer:
        pred_df.to_excel(writer, sheet_name="Predictions", index=False)
        eq_df.to_excel(writer, sheet_name="Backtest_Equity", index=False)
    print("[+] Отчет сохранен в betting_analytics_report.xlsx")
    print("\nПрограмма успешно завершила работу!")


if __name__ == "__main__":
    main()
