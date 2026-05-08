"""
AI仮想投資シミュレーター — ポートフォリオ自動構築スクリプト

【重要】
このスクリプトは仮想投資シミュレーター専用です。
実際の証券口座への接続・実注文は一切行いません。
選定銘柄・投資理由はシミュレーション目的の参考情報です。
過去データをもとに「6ヶ月前にこのポートフォリオを組んでいたら」という
仮定シナリオを可視化します。将来の運用成績を保証するものではありません。
"""

import yfinance as yf
import pandas as pd
import db
from datetime import datetime, timedelta

PICKS = [
    {
        "ticker": "8035.T",
        "name": "東京エレクトロン",
        "sector": "半導体製造装置",
        "weight": 0.13,
        "score": 92,
        "reason": (
            "【選定理由】AIデータセンター向け半導体製造装置で世界2位のシェア。"
            "HBM（高帯域メモリ）製造ラインへの投資が急増しており成膜装置の受注が拡大。"
            "TSMC・SK Hynixの設備投資計画が継続的に上方修正されており中期的な受注可視性が高い。"
            "【リスク】半導体景気の循環変動・米国の対中輸出規制強化による市場縮小リスクあり。"
        ),
    },
    {
        "ticker": "6857.T",
        "name": "アドバンテスト",
        "sector": "半導体テスト装置",
        "weight": 0.12,
        "score": 90,
        "reason": (
            "【選定理由】半導体テスト装置で世界トップシェア。"
            "NVIDIAのGPU・AI半導体の複雑化によりテスト工程時間が延長し装置需要が倍増傾向。"
            "SoC向け・HBM向けテスター両方で受注増加中。"
            "【リスク】特定顧客（NVIDIA）への依存度が高く同社の設備投資計画変更が業績に直結。"
        ),
    },
    {
        "ticker": "6920.T",
        "name": "レーザーテック",
        "sector": "半導体検査装置",
        "weight": 0.10,
        "score": 88,
        "reason": (
            "【選定理由】EUV露光マスク欠陥検査装置で世界唯一の量産メーカー。"
            "2nm以下の先端ノードへの移行で検査工程の重要性が増大し代替不可能なポジション。"
            "ASMLのEUV装置増産と連動した受注増加が期待できる。"
            "【リスク】株価ボラティリティが非常に高く短期的な株価変動リスクが大きい。"
        ),
    },
    {
        "ticker": "7011.T",
        "name": "三菱重工業",
        "sector": "防衛・エネルギー",
        "weight": 0.12,
        "score": 87,
        "reason": (
            "【選定理由】日本の防衛費GDP比2%への引き上げの最大受益企業。"
            "F-X次期戦闘機・イージス艦・スタンドオフミサイルなど大型プロジェクトを複数受注。"
            "原子力発電所の再稼働・新増設需要も業績押し上げ要因として加わる。"
            "【リスク】政府調達に依存するため政策変更が業績に影響。"
        ),
    },
    {
        "ticker": "5631.T",
        "name": "日本製鋼所",
        "sector": "防衛・原子力",
        "weight": 0.08,
        "score": 85,
        "reason": (
            "【選定理由】火砲（砲身）の国内唯一の製造メーカーとして防衛費拡大の直接受益。"
            "原子力圧力容器の世界的シェアを持ちグローバルな原発回帰トレンドの恩恵を享受。"
            "小型・特殊鋼材の高付加価値製品で参入障壁が高い。"
            "【リスク】製造能力に上限があり急激な受注増加への対応が課題。"
        ),
    },
    {
        "ticker": "8306.T",
        "name": "三菱UFJ FG",
        "sector": "金融・銀行",
        "weight": 0.10,
        "score": 83,
        "reason": (
            "【選定理由】日銀の利上げサイクル開始により国内貸出利ざやの改善が本格化。"
            "米国・ASEAN事業の高収益化が進み海外収益比率が向上。"
            "PBR改善のための自社株買い・増配継続で株主還元が拡大中。"
            "【リスク】景気後退時の不良債権増加リスク。急速な利上げによる含み損拡大。"
        ),
    },
    {
        "ticker": "8316.T",
        "name": "三井住友 FG",
        "sector": "金融・銀行",
        "weight": 0.05,
        "score": 82,
        "reason": (
            "【選定理由】利上げ恩恵と海外事業拡大のダブルドライバー。"
            "インドSBI銀行への出資による高成長アジア市場エクスポージャー。"
            "ROE改善目標と株主還元強化でバリュー投資家からの注目が高まっている。"
            "【リスク】海外事業の地政学リスク。与信コスト上昇懸念。"
        ),
    },
    {
        "ticker": "6861.T",
        "name": "キーエンス",
        "sector": "FA・自動化",
        "weight": 0.10,
        "score": 86,
        "reason": (
            "【選定理由】製造業のスマートファクトリー化・省人化投資の中核企業。"
            "営業利益率50%超の超高収益モデルを維持しながらグローバル展開を加速。"
            "人手不足が深刻化する中で自動化需要は構造的かつ長期的に拡大継続。"
            "【リスク】製造業の設備投資抑制局面で業績が悪化しやすい。高バリュエーション。"
        ),
    },
    {
        "ticker": "6146.T",
        "name": "ディスコ",
        "sector": "半導体精密加工",
        "weight": 0.10,
        "score": 84,
        "reason": (
            "【選定理由】半導体ウェハーのダイシング・研削装置で世界シェア約70%を独占。"
            "チップレット構造の普及でパッケージング工程が増加し精密切断需要が増大。"
            "AI半導体の大型化・薄型化トレンドがディスコ製品の重要性を一層高める。"
            "【リスク】半導体装置業界全体の景気循環に連動。単一製品への依存度の高さ。"
        ),
    },
    {
        "ticker": "4307.T",
        "name": "野村総合研究所",
        "sector": "DX・ITサービス",
        "weight": 0.10,
        "score": 81,
        "reason": (
            "【選定理由】金融機関・政府向けITサービスで国内最大手。"
            "DX推進・レガシーシステムのモダナイゼーション需要が安定的に積み上がる。"
            "生成AIを活用したシステム開発高度化フェーズへの移行で単価上昇が期待される。"
            "【リスク】人材不足によるコスト上昇。大型プロジェクトの失敗リスク。"
        ),
    },
]

BUY_DATE_OFFSET = 182


def get_historical_price(ticker: str, target_date: datetime):
    start = target_date - timedelta(days=5)
    end = target_date + timedelta(days=10)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
        )
        if hist.empty:
            return None, None
        price = float(hist.iloc[0]["Close"])
        date = hist.index[0].strftime("%Y-%m-%d")
        return price, date
    except Exception as e:
        print(f"  ERROR fetching {ticker}: {e}")
        return None, None


def compute_and_save_performance(holdings_data: list, remaining_cash: float, buy_date: datetime):
    """過去6ヶ月の日次ポートフォリオ価値を計算してDBに保存"""
    if not holdings_data:
        return

    tickers = [h["ticker"] for h in holdings_data]
    shares_map = {h["ticker"]: h["shares"] for h in holdings_data}
    buy_map = {h["ticker"]: h["buy_price"] for h in holdings_data}

    print("\n  [パフォーマンスデータを計算中...]")
    try:
        start_str = (buy_date - timedelta(days=5)).strftime("%Y-%m-%d")
        raw = yf.download(tickers, start=start_str, auto_adjust=True,
                          progress=False, threads=True)

        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            closes = raw[["Close"]].rename(columns={"Close": tickers[0]})

        conn = db.get_connection()
        conn.execute("DELETE FROM performance_history")

        rows = []
        for date, row in closes.iterrows():
            val = remaining_cash
            for tk in tickers:
                p = row.get(tk)
                val += (float(p) if p is not None and not pd.isna(p)
                        else buy_map[tk]) * shares_map[tk]
            rows.append((date.strftime("%Y-%m-%d"), round(val)))

        conn.executemany("INSERT OR REPLACE INTO performance_history VALUES (?,?)", rows)
        conn.commit()
        conn.close()
        print(f"  ✓  パフォーマンスデータ: {len(rows)} 日分保存完了")
    except Exception as e:
        print(f"  WARNING: パフォーマンスデータの計算をスキップ: {e}")


def run():
    db.init_db()
    conn = db.get_connection()

    conn.execute("UPDATE cash SET balance=?", (db.INITIAL_CASH,))
    conn.execute("DELETE FROM holdings")
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM candidates")
    conn.execute("DELETE FROM performance_history")
    conn.commit()

    target_date = datetime.now() - timedelta(days=BUY_DATE_OFFSET)
    print("\n" + "=" * 70)
    print("  AI 仮想投資シミュレーター — ポートフォリオ自動構築")
    print("  ※ これは仮想シミュレーションです。実際の投資判断ではありません。")
    print("=" * 70)
    print(f"  仮想購入日  : {target_date.strftime('%Y-%m-%d')} (約6ヶ月前の実際の終値)")
    print(f"  仮想資金    : ¥{db.INITIAL_CASH:>15,.0f}")
    print("=" * 70)

    now_str = datetime.now().strftime("%Y-%m-%d")
    total_invested = 0.0
    holdings_data = []

    for p in PICKS:
        ticker = p["ticker"]
        name = p["name"]
        weight = p["weight"]
        score = p["score"]
        reason = p["reason"]
        sector = p["sector"]

        conn.execute(
            "INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?)",
            (ticker, name, sector, score, reason, now_str),
        )

        budget = db.INITIAL_CASH * weight
        price, buy_date = get_historical_price(ticker, target_date)

        if price is None:
            print(f"  ✗  {name:<22} — データ取得失敗")
            continue

        shares = int(budget / price)
        if shares == 0:
            print(f"  ✗  {name:<22} — 株価が高すぎて購入不可 (¥{price:,.0f})")
            continue

        cost = price * shares
        conn.execute(
            "INSERT INTO transactions "
            "(datetime, type, ticker, company_name, shares, price, total, reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"{buy_date} 09:00:00", "buy", ticker, name, shares, price, cost, reason),
        )
        conn.execute(
            "INSERT OR REPLACE INTO holdings VALUES (?,?,?,?)",
            (ticker, name, shares, price),
        )
        conn.execute("UPDATE cash SET balance = balance - ?", (cost,))

        holdings_data.append({
            "ticker": ticker,
            "shares": shares,
            "buy_price": price,
        })
        total_invested += cost
        print(f"  ✓  {name:<22} ({ticker})  {shares:>5}株  @  ¥{price:>9,.0f}  =  ¥{cost:>12,.0f}")

    conn.commit()
    remaining = conn.execute("SELECT balance FROM cash WHERE id=1").fetchone()["balance"]
    conn.close()

    print("=" * 70)
    print(f"  仮想投資総額: ¥{total_invested:>15,.0f}")
    print(f"  仮想残り現金: ¥{remaining:>15,.0f}")
    print("=" * 70)

    # 6ヶ月分のパフォーマンスデータを計算・保存
    compute_and_save_performance(holdings_data, remaining, target_date)

    print("\n  完了! 以下のコマンドでサーバーを起動してください:")
    print("  python3 app.py")
    print("  → ブラウザで http://127.0.0.1:8080 を開く\n")


if __name__ == "__main__":
    run()
