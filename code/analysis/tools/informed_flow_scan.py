import pandas as pd
import numpy as np
import glob

def analyze_anonymous_flow(data_dir, horizons=[5, 10, 20]):
    trade_files = glob.glob(f"{data_dir}/trades_round_3_day_*.csv")
    price_files = glob.glob(f"{data_dir}/prices_round_3_day_*.csv")
    
    if not trade_files or not price_files:
        raise FileNotFoundError("Missing data files.")
        
    trades = []
    prices = []
    
    for tf in trade_files:
        df = pd.read_csv(tf, sep=';')
        day = int(tf.split('day_')[1].split('.')[0])
        df['day'] = day
        trades.append(df)
        
    for pf in price_files:
        df = pd.read_csv(pf, sep=';')
        prices.append(df)
        
    t_df = pd.concat(trades).sort_values(['day', 'timestamp'])
    p_df = pd.concat(prices).sort_values(['day', 'timestamp'])
    
    symbols = t_df['symbol'].unique()
    
    for sym in symbols:
        print(f"\n==============================")
        print(f"Scaning {sym} for Informed Flow")
        print(f"==============================")
        
        sym_p = p_df[p_df['product'] == sym].copy()
        sym_t = t_df[t_df['symbol'] == sym].copy()
        
        # Merge prices into trades
        # For simplicity, we just merge on exact timestamp
        merged = pd.merge(sym_t, sym_p[['day', 'timestamp', 'mid_price', 'bid_price_1', 'ask_price_1']], 
                          on=['day', 'timestamp'], how='inner')
        
        if merged.empty:
            continue
            
        # Infer trade direction
        # 1 = Taker Buy, -1 = Taker Sell
        merged['trade_side'] = 0
        merged.loc[merged['price'] >= merged['ask_price_1'], 'trade_side'] = 1
        merged.loc[merged['price'] <= merged['bid_price_1'], 'trade_side'] = -1
        
        # We only care about directional trades
        directional = merged[merged['trade_side'] != 0].copy()
        
        # Align with future returns
        sym_p = sym_p.sort_values(['day', 'timestamp'])
        for h in horizons:
            sym_p[f'mid_{h}'] = sym_p.groupby('day')['mid_price'].shift(-h)
            
        future_mids = sym_p[['day', 'timestamp'] + [f'mid_{h}' for h in horizons]]
        
        d_merged = pd.merge(directional, future_mids, on=['day', 'timestamp'], how='inner')
        
        for h in horizons:
            d_merged[f'ret_{h}'] = d_merged[f'mid_{h}'] - d_merged['mid_price']
            d_merged[f'edge_{h}'] = d_merged[f'ret_{h}'] * d_merged['trade_side']
            d_merged[f'hit_{h}'] = (d_merged[f'edge_{h}'] > 0).astype(int)
            
        # Group by trade size. Informed traders often execute in fixed sizes.
        summary = d_merged.groupby('quantity').agg(
            events=('quantity', 'size'),
            buys=('trade_side', lambda x: (x > 0).sum()),
            sells=('trade_side', lambda x: (x < 0).sum()),
            edge_5=('edge_5', 'mean'),
            hit_5=('hit_5', 'mean'),
            edge_10=('edge_10', 'mean'),
            hit_10=('hit_10', 'mean'),
            edge_20=('edge_20', 'mean'),
            hit_20=('hit_20', 'mean'),
        ).reset_index()
        
        # Filter for noise
        summary = summary[summary['events'] >= 10].sort_values(by='edge_20', ascending=False)
        
        if summary.empty:
            print("No significant size-based patterns found.")
        else:
            print("--- Profitability / Hit Rate by Trade Quantity ---")
            print(summary.head(10).to_string(index=False))

if __name__ == "__main__":
    analyze_anonymous_flow('/Users/sean_tsu_/Downloads/prosperity/IMCP2026/data/round3')
