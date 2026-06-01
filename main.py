"""
A股股票筛选工具 - 最小可运行版本

筛选条件：
  1. 涨跌幅 > 3%
  2. 成交额 > 5亿元
  3. 价格 5~80元
  4. 近20日均线向上（MA20今日 > MA20五日前）
"""

import sys
import time
import numpy as np
import pandas as pd
import akshare as ak
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

console = Console()


# ── 数据获取 ──────────────────────────────────────────────────────────────

def fetch_realtime() -> pd.DataFrame:
    """获取 A 股全量实时行情（沪深京）。"""
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "pct_chg",
        "成交额": "amount",
    })
    # 保留必要列，转数值
    cols = ["code", "name", "price", "pct_chg", "amount"]
    df = df[cols].copy()
    df["price"]   = pd.to_numeric(df["price"],   errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["amount"]  = pd.to_numeric(df["amount"],  errors="coerce")
    return df.dropna()


def fetch_ma20_slope(code: str) -> bool:
    """
    判断近20日均线是否向上：MA20(今日) > MA20(5日前)。
    获取失败时返回 False。
    """
    try:
        # 取最近 60 个交易日日线数据
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(pd.Timestamp.today() - pd.Timedelta(days=90)).strftime("%Y%m%d"),
            end_date=pd.Timestamp.today().strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is None or len(df) < 25:
            return False
        close = df["收盘"].astype(float)
        ma20 = close.rolling(20).mean()
        return float(ma20.iloc[-1]) > float(ma20.iloc[-6])
    except Exception:
        return False


# ── 筛选逻辑 ──────────────────────────────────────────────────────────────

FILTER_PCT_CHG  = 3.0          # 涨跌幅下限（%）
FILTER_AMOUNT   = 5e8          # 成交额下限（元）
FILTER_PRICE_LO = 5.0          # 价格下限（元）
FILTER_PRICE_HI = 80.0         # 价格上限（元）


def apply_quick_filters(df: pd.DataFrame) -> pd.DataFrame:
    """用实时行情数据做快速初筛（无需网络请求）。"""
    mask = (
        (df["pct_chg"] > FILTER_PCT_CHG) &
        (df["amount"]  > FILTER_AMOUNT)  &
        (df["price"]   >= FILTER_PRICE_LO) &
        (df["price"]   <= FILTER_PRICE_HI)
    )
    return df[mask].reset_index(drop=True)


def apply_ma_filter(candidates: pd.DataFrame) -> pd.DataFrame:
    """对初筛结果逐一判断均线方向（需下载历史数据，较慢）。"""
    passed = []
    total = len(candidates)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("正在验证均线条件...", total=total)
        for _, row in candidates.iterrows():
            progress.update(task, advance=1,
                            description=f"均线验证 {row['code']} ({_+1}/{total})")
            if fetch_ma20_slope(row["code"]):
                passed.append(row)
            time.sleep(0.05)   # 避免请求过于密集

    return pd.DataFrame(passed).reset_index(drop=True) if passed else pd.DataFrame()


# ── 输出 ──────────────────────────────────────────────────────────────────

def print_results(df: pd.DataFrame) -> None:
    if df.empty:
        rprint("\n[yellow]未找到符合条件的股票。[/yellow]")
        return

    table = Table(title=f"A股筛选结果  共 {len(df)} 只", show_lines=True)
    table.add_column("序号",   justify="right",  style="dim")
    table.add_column("股票代码", justify="center", style="cyan")
    table.add_column("股票名称", justify="left")
    table.add_column("最新价(元)", justify="right", style="bold")
    table.add_column("涨跌幅(%)", justify="right")
    table.add_column("成交额(亿元)", justify="right")

    for i, row in df.iterrows():
        pct_str    = f"{row['pct_chg']:+.2f}%"
        amount_str = f"{row['amount'] / 1e8:.2f}"
        pct_color  = "red" if row["pct_chg"] > 0 else "green"

        table.add_row(
            str(i + 1),
            row["code"],
            row["name"],
            f"{row['price']:.2f}",
            f"[{pct_color}]{pct_str}[/{pct_color}]",
            amount_str,
        )

    console.print(table)


# ── 入口 ──────────────────────────────────────────────────────────────────

def main() -> None:
    console.rule("[bold blue]A股股票筛选工具[/bold blue]")
    console.print(
        f"筛选条件：涨跌幅>[bold]{FILTER_PCT_CHG}%[/bold]  "
        f"成交额>[bold]{FILTER_AMOUNT/1e8:.0f}亿[/bold]  "
        f"价格[bold]{FILTER_PRICE_LO}~{FILTER_PRICE_HI}元[/bold]  "
        f"[bold]MA20向上[/bold]"
    )
    console.rule()

    # 第一步：拉取实时行情
    with console.status("正在获取 A 股实时行情..."):
        try:
            realtime_df = fetch_realtime()
        except Exception as e:
            rprint(f"[red]获取实时行情失败：{e}[/red]")
            sys.exit(1)
    console.print(f"[green]✓[/green] 共获取 {len(realtime_df)} 只股票实时数据")

    # 第二步：快速初筛
    candidates = apply_quick_filters(realtime_df)
    console.print(f"[green]✓[/green] 初筛（涨幅/成交额/价格）通过 {len(candidates)} 只")

    if candidates.empty:
        rprint("\n[yellow]初筛无结果，请确认今日行情数据是否已更新（非交易日/盘前数据可能为空）。[/yellow]")
        sys.exit(0)

    # 第三步：均线验证（逐一下载历史数据）
    console.print(f"开始对 {len(candidates)} 只股票验证 MA20 趋势...")
    result_df = apply_ma_filter(candidates)

    # 输出结果
    console.rule()
    print_results(result_df)


if __name__ == "__main__":
    main()
