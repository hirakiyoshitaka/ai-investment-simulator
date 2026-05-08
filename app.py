"""
AI仮想投資シミュレーター — Flask バックエンド (ポート 8080)
※ 仮想投資シミュレーション専用。実際の証券口座への接続・実注文は一切行いません。
"""

from flask import Flask, render_template, jsonify, request
import yfinance as yf
import db
from datetime import datetime
import time
import threading
import subprocess
import sys

app = Flask(__name__)

_price_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300

POPULAR = [
    ("8035.T", "東京エレクトロン"), ("6857.T", "アドバンテスト"),
    ("6920.T", "レーザーテック"),   ("7011.T", "三菱重工業"),
    ("5631.T", "日本製鋼所"),       ("8306.T", "三菱UFJ FG"),
    ("6861.T", "キーエンス"),       ("6146.T", "ディスコ"),
    ("7203.T", "トヨタ自動車"),     ("9984.T", "ソフトバンクG"),
    ("7974.T", "任天堂"),           ("6758.T", "ソニーグループ"),
]


def normalize(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if t.endswith(".T") else t + ".T"


def cached_price(ticker: str):
    with _cache_lock:
        c = _price_cache.get(ticker)
    if c and time.time() - c[1] < CACHE_TTL:
        return c[0], c[2]
    return None, None


def fetch_one(ticker: str):
    try:
        info = yf.Ticker(ticker).info
        price = (info.get("currentPrice") or info.get("regularMarketPrice")
                 or info.get("previousClose"))
        name = info.get("longName") or info.get("shortName") or ticker
        if price:
            with _cache_lock:
                _price_cache[ticker] = (price, time.time(), name)
            return price, name
    except Exception as e:
        print(f"fetch_one({ticker}): {e}")
    return None, ticker


@app.route("/api/market_status")
def api_market_status():
    """東京証券取引所の開閉状態を返す"""
    try:
        info = yf.Ticker("8035.T").fast_info
        state = getattr(info, "market_state", None) or "UNKNOWN"
    except Exception:
        state = "UNKNOWN"

    from datetime import timezone, timedelta
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    weekday = now_jst.weekday()  # 0=月, 6=日
    hour = now_jst.hour
    minute = now_jst.minute
    time_val = hour * 100 + minute

    # 平日9:00〜15:30が通常取引時間
    is_trading_hours = (weekday < 5) and (900 <= time_val <= 1530)

    if is_trading_hours and state not in ("CLOSED", "PRE", "POST"):
        label = "取引時間中"
        color = "green"
        price_note = "リアルタイム株価を使用"
    else:
        label = "取引時間外"
        color = "muted"
        if weekday >= 5:
            reason = "土日休場"
        elif time_val < 900:
            reason = "開場前"
        elif time_val > 1530:
            reason = "閉場後"
        else:
            reason = "休場日"
        price_note = f"直近の終値を使用（{reason}）"

    return jsonify({
        "label": label,
        "color": color,
        "price_note": price_note,
        "is_open": color == "green",
        "jst_time": now_jst.strftime("%H:%M"),
        "note": "仮想シミュレーターは24時間いつでも売買できます",
    })


def fetch_prices_background(tickers: list):
    for t in tickers:
        fetch_one(t)


@app.route("/")
def index():
    return render_template("index.html", popular=POPULAR)


@app.route("/guide")
def guide():
    return render_template("guide.html")


@app.route("/api/portfolio")
def api_portfolio():
    conn = db.get_connection()
    cash = conn.execute("SELECT balance FROM cash WHERE id=1").fetchone()["balance"]
    rows = conn.execute("SELECT * FROM holdings WHERE shares > 0").fetchall()
    conn.close()

    holdings = []
    total_market = 0.0
    missing = []

    for r in rows:
        price, name = cached_price(r["ticker"])
        stale = price is None
        if stale:
            price = r["avg_buy_price"]
            missing.append(r["ticker"])

        mv = price * r["shares"]
        pnl = (price - r["avg_buy_price"]) * r["shares"]
        total_market += mv
        holdings.append({
            "ticker":        r["ticker"],
            "name":          r["company_name"] or name or r["ticker"],
            "shares":        r["shares"],
            "avg_buy_price": r["avg_buy_price"],
            "current_price": price,
            "market_value":  mv,
            "unrealized_pnl": pnl,
            "unrealized_pct": (price - r["avg_buy_price"]) / r["avg_buy_price"] * 100,
            "stale":         stale,
        })

    if missing:
        threading.Thread(target=fetch_prices_background,
                         args=(missing,), daemon=True).start()

    holdings.sort(key=lambda x: x["market_value"], reverse=True)
    total = cash + total_market
    pnl_tot = total - db.INITIAL_CASH
    return jsonify({
        "cash":               cash,
        "total_market_value": total_market,
        "total_value":        total,
        "total_pnl":          pnl_tot,
        "total_pnl_pct":      pnl_tot / db.INITIAL_CASH * 100,
        "initial_cash":       db.INITIAL_CASH,
        "holdings":           holdings,
        "has_stale":          bool(missing),
    })


@app.route("/api/refresh_prices")
def api_refresh_prices():
    """保有銘柄の株価をバックグラウンドで更新（即時レスポンス）"""
    conn = db.get_connection()
    rows = conn.execute("SELECT ticker FROM holdings WHERE shares > 0").fetchall()
    conn.close()
    tickers = [r["ticker"] for r in rows]
    if tickers:
        threading.Thread(target=fetch_prices_background,
                         args=(tickers,), daemon=True).start()
    return jsonify({"status": "updating", "count": len(tickers)})


@app.route("/api/stats")
def api_stats():
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM holdings WHERE shares > 0").fetchall()
    conn.close()

    if not rows:
        return jsonify({"win_rate": 0, "winners": 0, "losers": 0,
                        "best": None, "worst": None, "avg_pnl_pct": 0, "total": 0})

    results = []
    for r in rows:
        price, _ = cached_price(r["ticker"])
        price = price or r["avg_buy_price"]
        pnl_pct = (price - r["avg_buy_price"]) / r["avg_buy_price"] * 100
        results.append({"ticker": r["ticker"], "name": r["company_name"], "pnl_pct": pnl_pct})

    winners = [x for x in results if x["pnl_pct"] >= 0]
    losers  = [x for x in results if x["pnl_pct"] < 0]
    return jsonify({
        "win_rate":    len(winners) / len(results) * 100,
        "winners":     len(winners),
        "losers":      len(losers),
        "total":       len(results),
        "best":        max(results, key=lambda x: x["pnl_pct"]),
        "worst":       min(results, key=lambda x: x["pnl_pct"]),
        "avg_pnl_pct": sum(x["pnl_pct"] for x in results) / len(results),
    })


@app.route("/api/candidates")
def api_candidates():
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM candidates ORDER BY score DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/performance")
def api_performance():
    """DBから事前計算済みパフォーマンスデータを即返す（高速）"""
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT date, value FROM performance_history ORDER BY date"
    ).fetchall()
    conn.close()
    return jsonify([{"date": r["date"], "value": r["value"]} for r in rows])


@app.route("/api/quote/<path:ticker>")
def api_quote(ticker):
    ticker = normalize(ticker)
    price, name = fetch_one(ticker)
    if not price:
        return jsonify({"error": "銘柄が見つかりません"}), 404
    try:
        info = yf.Ticker(ticker).info
        prev = info.get("previousClose", price) or price
        chg = price - prev
        return jsonify({
            "ticker": ticker, "name": name, "price": price,
            "prev_close": prev, "change": chg,
            "change_pct": chg / prev * 100 if prev else 0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/chart/<path:ticker>")
def api_chart(ticker):
    ticker = normalize(ticker)
    period = request.args.get("period", "3mo")
    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return jsonify({"error": "データなし"}), 404
        return jsonify([
            {"date": d.strftime("%Y-%m-%d"),
             "open": round(r["Open"], 1), "high": round(r["High"], 1),
             "low":  round(r["Low"],  1), "close": round(r["Close"], 1),
             "volume": int(r["Volume"])}
            for d, r in hist.iterrows()
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/buy", methods=["POST"])
def api_buy():
    body = request.get_json()
    ticker = normalize(body.get("ticker", ""))
    shares = int(body.get("shares", 0))
    reason = body.get("reason", "手動売買（仮想）")
    if shares <= 0:
        return jsonify({"error": "数量は1以上で入力してください"}), 400

    price, name = fetch_one(ticker)
    if not price:
        return jsonify({"error": "株価の取得に失敗しました"}), 400

    cost = price * shares
    conn = db.get_connection()
    cash = conn.execute("SELECT balance FROM cash WHERE id=1").fetchone()["balance"]
    if cash < cost:
        conn.close()
        return jsonify({"error": f"仮想資金不足。必要: ¥{cost:,.0f} / 残高: ¥{cash:,.0f}"}), 400

    conn.execute("UPDATE cash SET balance = balance - ? WHERE id=1", (cost,))
    ex = conn.execute("SELECT * FROM holdings WHERE ticker=?", (ticker,)).fetchone()
    if ex:
        nq = ex["shares"] + shares
        nav = (ex["avg_buy_price"] * ex["shares"] + price * shares) / nq
        conn.execute("UPDATE holdings SET shares=?, avg_buy_price=? WHERE ticker=?",
                     (nq, nav, ticker))
    else:
        conn.execute("INSERT INTO holdings VALUES (?,?,?,?)",
                     (ticker, name, shares, price))

    conn.execute(
        "INSERT INTO transactions "
        "(datetime,type,ticker,company_name,shares,price,total,reason) VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "buy", ticker, name, shares, price, cost, reason),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True,
                    "message": f"[仮想] {name}  {shares}株  @  ¥{price:,.0f} で購入"})


@app.route("/api/sell", methods=["POST"])
def api_sell():
    body = request.get_json()
    ticker = normalize(body.get("ticker", ""))
    shares = int(body.get("shares", 0))
    reason = body.get("reason", "手動売却（仮想）")
    if shares <= 0:
        return jsonify({"error": "数量は1以上で入力してください"}), 400

    conn = db.get_connection()
    ex = conn.execute("SELECT * FROM holdings WHERE ticker=?", (ticker,)).fetchone()
    if not ex or ex["shares"] < shares:
        conn.close()
        return jsonify({"error": "保有株数が不足しています"}), 400

    price, name = fetch_one(ticker)
    if not price:
        conn.close()
        return jsonify({"error": "株価の取得に失敗しました"}), 400

    proceeds = price * shares
    realized_pnl = (price - ex["avg_buy_price"]) * shares

    conn.execute("UPDATE cash SET balance = balance + ? WHERE id=1", (proceeds,))
    nq = ex["shares"] - shares
    if nq == 0:
        conn.execute("DELETE FROM holdings WHERE ticker=?", (ticker,))
    else:
        conn.execute("UPDATE holdings SET shares=? WHERE ticker=?", (nq, ticker))

    conn.execute(
        "INSERT INTO transactions "
        "(datetime,type,ticker,company_name,shares,price,total,reason) VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "sell", ticker, ex["company_name"] or name,
         shares, price, proceeds,
         f"{reason} | 仮想実現損益: {'+' if realized_pnl>=0 else ''}¥{realized_pnl:,.0f}"),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True,
                    "message": f"[仮想] {name or ticker}  {shares}株  @  ¥{price:,.0f} で売却"})


@app.route("/api/transactions")
def api_transactions():
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY datetime DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/reset", methods=["POST"])
def api_reset():
    conn = db.get_connection()
    conn.execute("UPDATE cash SET balance=?", (db.INITIAL_CASH,))
    conn.execute("DELETE FROM holdings")
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM candidates")
    conn.execute("DELETE FROM performance_history")
    conn.commit()
    conn.close()
    with _cache_lock:
        _price_cache.clear()
    return jsonify({"success": True, "message": "ポートフォリオをリセットしました"})


def open_browsers():
    """サーバー起動後にSafariとChromeを自動で開く"""
    time.sleep(1.5)
    # Safari でガイドページ
    subprocess.Popen(["open", "-a", "Safari", "http://127.0.0.1:8080/guide"])
    time.sleep(0.5)
    # Chrome でシミュレーター本体
    subprocess.Popen(["open", "-a", "Google Chrome", "http://127.0.0.1:8080"])
    print("\n  ✓ Safari  → http://127.0.0.1:8080/guide  (解説)")
    print("  ✓ Chrome  → http://127.0.0.1:8080        (シミュレーター)")
    print("  左右に並べてご利用ください\n")


if __name__ == "__main__":
    db.init_db()
    print("\n" + "=" * 55)
    print("  AI仮想投資シミュレーター 起動中...")
    print("  ※ 仮想シミュレーション専用 — 実注文なし")
    print("  ブラウザ: http://127.0.0.1:8080")
    print("=" * 55)
    threading.Thread(target=open_browsers, daemon=True).start()
    app.run(debug=False, port=8080, host="127.0.0.1", threaded=True)
