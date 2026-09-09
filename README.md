# 🤖 Laptop Sniper Bot

## Overview
Ye bot Uniswap (Base chain) par LAPTOP token ke liye automatic liquidity detection karke instant buy karta hai.

## Features
- ✅ V2 + V3 dono versions support
- ✅ Automatic pair/pool detection (factory event monitoring)
- ✅ Start par mojood pair/pool bhi check karta hai
- ✅ Instant buy jab liquidity add ho
- ✅ 3-time retry logic (agar fail ho)
- ✅ `ONE_TIME_BUY` sab threads par lagu — sirf ek buy
- ✅ Railway par 24/7 auto-run

## Setup

### 1. Bot Wallet Banao
MetaMask → Add Account → "Bot Wallet" → Base network add karo → 0.01+ ETH add karo

### 2. Private Key Nikalein
Bot Wallet → ⋮ → Account details → Show private key → Copy (`0x...` se shuru, 66 characters)

### 3. GitHub mein Upload
New repository → ye files upload karo → Commit
**`.env` file kabhi commit mat karna** — `.gitignore` mein already blocked hai.

### 4. Railway par Deploy
railway.app → GitHub login → Deploy from GitHub repo → `laptop-sniper-bot`

### 5. Variables Set Karo
Railway → Variables tab (details ke liye `.env.example` dekho):
- `PRIV_KEY` = `0x...` (bot wallet ki private key)
- `BUY_AMOUNT_ETH` = `0.005` (ya jitna ETH se buy karna ho)
- `BASE_RPC` = apna RPC (public RPC rate-limit karta hai — Alchemy/QuickNode behtar hai)

### 6. Logs Check Karo
Railway → Deployments → View Logs

## Local Testing
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python pair_finder.py     # pair/pool mojood hai ya nahi, ye check karta hai
python bot.py             # bot chalao
```

## How It Works
1. Start par V2/V3 factory se pehle se mojood pair/pool check karta hai
2. Na mile to factory ke `PairCreated`/`PoolCreated` events monitor karta hai
3. Liquidity add hote hi buy transaction bhej deta hai
4. 3 baar retry (agar fail ho)

## ⚠️ Zaroori Baatein
- **V3 buy par slippage protection nahi hai** (`amountOutMinimum = 0`). Sandwich attack ka risk hai — chhoti `BUY_AMOUNT_ETH` se test karo.
- Bot naya/unaudited token kharidta hai. Sirf utna ETH rakho jitna khone ka afsos na ho.
- Bot wallet mein sirf buy amount + gas rakho, apna main wallet kabhi use mat karo.

## Support
Kisi bhi error ke liye Railway logs check karo!
