import os
import time
import json
import threading
from datetime import datetime, timezone
from web3 import Web3

try:
    from web3.middleware import geth_poa_middleware as POA_MIDDLEWARE
except ImportError:
    from web3.middleware import ExtraDataToPOAMiddleware as POA_MIDDLEWARE

# ==================== CONFIG ====================
RPC_URL = os.getenv("BASE_RPC", "https://mainnet.base.org")
PRIVATE_KEY = os.getenv("PRIV_KEY", "").strip()
TOKEN = Web3.to_checksum_address("0xB095274743941e953c746F9C228DA9c18Bb6ec29")
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
CHAIN_ID = 8453

V2_ROUTER = Web3.to_checksum_address("0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24")
V3_ROUTER = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")
V2_FACTORY = Web3.to_checksum_address("0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6")
V3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")

V2_PAIR = os.getenv("V2_PAIR_ADDRESS", "").strip()
V3_POOL = os.getenv("V3_POOL_ADDRESS", "").strip()
AUTO_V2 = os.getenv("AUTO_DETECT_V2", "true").lower() == "true"
AUTO_V3 = os.getenv("AUTO_DETECT_V3", "true").lower() == "true"
V3_POOL_FEE = int(os.getenv("V3_POOL_FEE", "500"))

# ==================== BUY SETTINGS ====================
BUY_AMOUNT_ETH = float(os.getenv("BUY_AMOUNT_ETH", "0.0014"))
SLIPPAGE_PERCENT = float(os.getenv("SLIPPAGE_PERCENT", "40"))
MAX_FEE_GWEI = float(os.getenv("MAX_FEE_GWEI", "220"))
MAX_PRIORITY_GWEI = float(os.getenv("MAX_PRIORITY_GWEI", "20"))
LIQUIDITY_THRESHOLD_PERCENT = float(os.getenv("LIQUIDITY_THRESHOLD", "3"))
POLL_SECONDS = 1
ONE_TIME_BUY = os.getenv("ONE_TIME_BUY", "true").lower() == "true"
MAX_BUY_ATTEMPTS = 10

STATUS_FILE = os.getenv("STATUS_FILE", "bot_status.json")
BUYS_FILE = os.getenv("BUYS_FILE", "buys.json")

# ==================== ABIs ====================
V2_PAIR_ABI = [
    {"name": "token0", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"name": "getReserves", "type": "function", "stateMutability": "view",
     "inputs": [],
     "outputs": [{"name": "reserve0", "type": "uint112"},
                 {"name": "reserve1", "type": "uint112"},
                 {"name": "blockTimestampLast", "type": "uint32"}]},
]

V3_POOL_ABI = [
    {"name": "liquidity", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint128"}]},
]

V2_FACTORY_ABI = [
    {"name": "getPair", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "outputs": [{"name": "pair", "type": "address"}]},
]

V3_FACTORY_ABI = [
    {"name": "getPool", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"},
                {"name": "fee", "type": "uint24"}],
     "outputs": [{"name": "pool", "type": "address"}]},
]

V2_ROUTER_ABI = [
    {"name": "getAmountsOut", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}]},
    {"name": "swapExactETHForTokensSupportingFeeOnTransferTokens", "type": "function",
     "stateMutability": "payable",
     "inputs": [{"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}],
     "outputs": []},
]

V3_ROUTER_ABI = [
    {"name": "exactInputSingle", "type": "function", "stateMutability": "payable",
     "inputs": [{"components": [
         {"name": "tokenIn", "type": "address"},
         {"name": "tokenOut", "type": "address"},
         {"name": "fee", "type": "uint24"},
         {"name": "recipient", "type": "address"},
         {"name": "amountIn", "type": "uint256"},
         {"name": "amountOutMinimum", "type": "uint256"},
         {"name": "sqrtPriceLimitX96", "type": "uint160"}],
         "name": "params", "type": "tuple"}],
     "outputs": [{"name": "amountOut", "type": "uint256"}]},
]

FEE_TIERS = [100, 500, 3000, 10000]
ZERO_ADDR = "0x" + "0" * 40

def _topic(text):
    h = Web3.keccak(text=text)
    h = h.hex() if not isinstance(h, str) else h
    return h if h.startswith("0x") else "0x" + h

PAIR_SIG = _topic("PairCreated(address,address,address,uint256)")
POOL_SIG = _topic("PoolCreated(address,address,uint24,int24,address)")
TOKEN_TOPIC = "0x" + "0" * 24 + TOKEN[2:].lower()

# ==================== GLOBALS ====================
w3 = None
acct = None
v2_router = None
v3_router = None
bought = threading.Event()
status = {"running": False, "mode": "", "found_v2_pair": "", "found_v3_pool": "",
          "last_buy": None, "buys": [], "error": None, "wallet": "", "eth_balance": 0.0}
status_lock = threading.Lock()

def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def save_status():
    with status_lock:
        try:
            with open(STATUS_FILE, "w") as f:
                json.dump(status, f, indent=2, default=str)
        except OSError as e:
            log(f"⚠️ status file error: {e}")

def set_error(e):
    status["error"] = str(e)[:300]
    save_status()

def add_buy(tx_hash, version):
    entry = {"tx_hash": tx_hash, "version": version, "amount_eth": BUY_AMOUNT_ETH,
             "time": datetime.now(timezone.utc).isoformat(),
             "link": f"https://basescan.org/tx/{tx_hash}"}
    with status_lock:
        status["buys"].append(entry)
        status["last_buy"] = entry
    save_status()
    try:
        with open(BUYS_FILE) as f:
            buys = json.load(f)
        if not isinstance(buys, list):
            buys = []
    except (OSError, ValueError):
        buys = []
    buys.append(entry)
    try:
        with open(BUYS_FILE, "w") as f:
            json.dump(buys, f, indent=2)
    except OSError as e:
        log(f"⚠️ buys file error: {e}")

def _raw_tx(signed):
    return getattr(signed, "raw_transaction", None) or signed.rawTransaction

def _gas_fields():
    return {
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "chainId": CHAIN_ID,
        "maxFeePerGas": w3.to_wei(MAX_FEE_GWEI, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(MAX_PRIORITY_GWEI, "gwei"),
    }

def _send(tx, version):
    try:
        signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(_raw_tx(signed)).hex()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash
        log(f"🚀🚀🚀 TX SENT: {tx_hash}")
        
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt["status"] == 1:
            log(f"✅✅✅✅✅ {version} BUY SUCCESS: https://basescan.org/tx/{tx_hash}")
            return tx_hash
        else:
            log(f"❌ {version} REVERTED: {tx_hash}")
            return None
    except Exception as e:
        log(f"❌ _send error: {e}")
        return None

# ==================== BUY FUNCTIONS ====================
def buy_v2(amount_in_wei):
    path = [WETH, TOKEN]
    try:
        amounts = v2_router.functions.getAmountsOut(amount_in_wei, path).call()
        expected_out = amounts[-1]
        amount_out_min = int(expected_out * (100 - SLIPPAGE_PERCENT) / 100)
        
        log(f"💰💰💰 V2: {expected_out / 10**18:.2f} tokens expected")
        log(f"🎯 Min: {amount_out_min / 10**18:.2f} (slippage {SLIPPAGE_PERCENT}%)")
        log(f"⚠️ 25% tax - you get ~{expected_out * 0.75 / 10**18:.2f}")
        
        tx = v2_router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
            amount_out_min, path, acct.address, int(time.time()) + 300
        ).build_transaction({
            "from": acct.address,
            "value": amount_in_wei,
            "gas": 600000,
            **_gas_fields()
        })
        return _send(tx, "V2")
    except Exception as e:
        log(f"❌ V2 buy error: {e}")
        return None

def buy_v3(amount_in_wei, fee=None):
    fee = V3_POOL_FEE if fee is None else fee
    try:
        log(f"💰💰💰 V3 BUY: {fee} fee, {BUY_AMOUNT_ETH} ETH")
        log(f"⚠️ 25% tax - expect 75% of tokens")
        
        params = (WETH, TOKEN, int(fee), acct.address, amount_in_wei, 0, 0)
        
        tx = v3_router.functions.exactInputSingle(params).build_transaction({
            "from": acct.address,
            "value": amount_in_wei,
            "gas": 700000,
            **_gas_fields()
        })
        return _send(tx, "V3")
    except Exception as e:
        log(f"❌ V3 buy error: {e}")
        return None

def try_buy(fn, amount_wei, version):
    if ONE_TIME_BUY and bought.is_set():
        return False
    
    log(f"🔥🔥🔥🔥🔥 BUY TRIGGERED ON {version}! MAX ATTEMPTS: {MAX_BUY_ATTEMPTS}")
    log(f"⚠️ HIGH TAX: 25% - you receive 75% of tokens")
    
    for attempt in range(1, MAX_BUY_ATTEMPTS + 1):
        log(f"🛒🛒 {version} attempt {attempt}/{MAX_BUY_ATTEMPTS} ...")
        try:
            tx_hash = fn(amount_wei)
            if tx_hash:
                add_buy(tx_hash, version)
                bought.set()
                log(f"🎉🎉🎉🎉🎉 {version} BUY COMPLETE! Tx: {tx_hash}")
                return True
            log(f"⚠️ Attempt {attempt} no hash, retrying...")
        except Exception as e:
            log(f"⚠️ Attempt {attempt} FAILED: {e}")
            set_error(e)
        
        if attempt < MAX_BUY_ATTEMPTS:
            time.sleep(0.5)
    
    log(f"❌❌❌ {version} FAILED after {MAX_BUY_ATTEMPTS} attempts!")
    return False

# ==================== LOG PARSING ====================
def _data_hex(entry):
    data = entry["data"]
    if isinstance(data, (bytes, bytearray)):
        return "0x" + bytes(data).hex()
    return data if data.startswith("0x") else "0x" + data

def _word(data_hex, index):
    start = 2 + 64 * index
    return data_hex[start:start + 64]

def _addr_from_word(word):
    return Web3.to_checksum_address("0x" + word[24:])

# ==================== FACTORY WATCHERS ====================
def _scan(factory_addr, sig, from_block, to_block):
    for topics in ([sig, TOKEN_TOPIC], [sig, None, TOKEN_TOPIC]):
        try:
            logs = w3.eth.get_logs({"fromBlock": from_block, "toBlock": to_block,
                                    "address": factory_addr, "topics": topics})
        except Exception:
            continue
        if logs:
            return logs[0]
    return None

def watch_v2_factory():
    log("🔎 V2 AUTO-MODE: Factory se naya LAPTOP pair dhoondh raha hoon...")
    last = w3.eth.block_number
    check_count = 0
    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            cur = w3.eth.block_number
            if cur > last:
                entry = _scan(V2_FACTORY, PAIR_SIG, last + 1, cur)
                last = cur
                check_count += 1
                if check_count % 6 == 0:
                    log(f"⏳ V2 factory check #{check_count} (block {cur})")
                if entry:
                    pair = _addr_from_word(_word(_data_hex(entry), 0))
                    log(f"🆕🆕🆕 NAYA V2 PAIR BANA: {pair}")
                    status["found_v2_pair"] = pair
                    save_status()
                    monitor_v2(pair, buy_now=True)
                    return
            else:
                last = cur
            time.sleep(0.3)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V2 factory error: {e}")
            time.sleep(1)

def watch_v3_factory():
    log("🔎 V3 AUTO-MODE: Factory se naya LAPTOP pool dhoondh raha hoon...")
    last = w3.eth.block_number
    check_count = 0
    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            cur = w3.eth.block_number
            if cur > last:
                entry = _scan(V3_FACTORY, POOL_SIG, last + 1, cur)
                last = cur
                check_count += 1
                if check_count % 6 == 0:
                    log(f"⏳ V3 factory check #{check_count} (block {cur})")
                if entry:
                    data = _data_hex(entry)
                    pool = _addr_from_word(_word(data, 1))
                    fee = V3_POOL_FEE
                    topics = entry["topics"]
                    if len(topics) > 3:
                        raw = topics[3]
                        fee = int(raw.hex() if not isinstance(raw, str) else raw, 16)
                    log(f"🆕🆕🆕 NAYA V3 POOL BANA: {pool} (fee {fee})")
                    status["found_v3_pool"] = pool
                    save_status()
                    monitor_v3(pool, fee=fee)
                    return
            else:
                last = cur
            time.sleep(0.3)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V3 factory error: {e}")
            time.sleep(1)

# ==================== MONITORS ====================
def monitor_v2(pair_address, buy_now=False):
    log(f"📍 V2 MONITOR START: {pair_address}")
    log(f"⚡ ULTRA MODE: {LIQUIDITY_THRESHOLD_PERCENT}% = BUY!")
    log(f"⚠️ 25% tax - will receive 75%")
    
    try:
        pair = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=V2_PAIR_ABI)
        token0 = pair.functions.token0().call()
        is_token0 = token0.lower() == TOKEN.lower()
        log(f"V2 pair: {pair_address} | LAPTOP token0: {is_token0}")

        r0, r1, _ = pair.functions.getReserves().call()
        base_reserve = r0 if is_token0 else r1
        log(f"👀 V2 initial reserve: {base_reserve / 10**18:.4f} LAPTOP")

        if buy_now and base_reserve > 10**15:
            log("💧💧💧 V2 liquidity ALREADY ADDED — FORAN BUY!")
            if try_buy(buy_v2, w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V2") and ONE_TIME_BUY:
                return
        base_reserve = max(base_reserve, 1)

        check_count = 0
        while not (ONE_TIME_BUY and bought.is_set()):
            try:
                r0, r1, _ = pair.functions.getReserves().call()
                reserve = r0 if is_token0 else r1
                check_count += 1
                
                threshold = base_reserve * (1 + LIQUIDITY_THRESHOLD_PERCENT / 100)
                log(f"✅ V2 check #{check_count}: {reserve / 10**18:.4f} | Need: {threshold / 10**18:.4f}")
                
                if reserve > threshold:
                    increase_pct = ((reserve - base_reserve) / base_reserve) * 100
                    log(f"💧💧💧 V2 LIQUIDITY INCREASE! +{increase_pct:.1f}%")
                    log(f"🚀🚀🚀 AUTO-BUY TRIGGERED ON V2!")
                    if try_buy(buy_v2, w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V2") and ONE_TIME_BUY:
                        log("✅ V2 buy COMPLETE!")
                        return
                    base_reserve = reserve
                else:
                    remaining = threshold - reserve
                    log(f"⏳ V2 waiting... need +{remaining / 10**18:.4f} more")
                
                time.sleep(POLL_SECONDS)
            except Exception as e:
                set_error(e)
                log(f"⚠️ V2 monitor error: {e}")
                time.sleep(1)
    except Exception as e:
        set_error(e)
        log(f"❌ V2 monitor setup FAIL: {e}")

def monitor_v3(pool_address, fee=None):
    fee = V3_POOL_FEE if fee is None else fee
    log(f"📍 V3 MONITOR START: {pool_address} (fee {fee})")
    log(f"⚡ ULTRA MODE: {LIQUIDITY_THRESHOLD_PERCENT}% = BUY!")
    log(f"⚠️ 25% tax - will receive 75%")
    
    try:
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=V3_POOL_ABI)
        base_liq = pool.functions.liquidity().call()
        log(f"👀 V3 initial liquidity: {base_liq}")

        def _buy():
            return try_buy(lambda amt: buy_v3(amt, fee), w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V3")

        check_count = 0
        while not (ONE_TIME_BUY and bought.is_set()):
            try:
                liq = pool.functions.liquidity().call()
                check_count += 1
                
                threshold = int(base_liq * (1 + LIQUIDITY_THRESHOLD_PERCENT / 100))
                log(f"✅ V3 check #{check_count}: {liq} | Need: {threshold}")
                
                if base_liq == 0 and liq > 0:
                    log(f"💧💧💧 V3 FIRST LIQUIDITY ADDED! 0 → {liq}")
                    log(f"🚀🚀🚀 AUTO-BUY TRIGGERED ON V3!")
                    if _buy() and ONE_TIME_BUY:
                        log("✅ V3 buy COMPLETE!")
                        return
                    base_liq = liq
                elif base_liq > 0 and liq > threshold:
                    increase_pct = ((liq - base_liq) / base_liq) * 100
                    log(f"💧💧💧 V3 LIQUIDITY INCREASE! +{increase_pct:.1f}%")
                    log(f"🚀🚀🚀 AUTO-BUY TRIGGERED ON V3!")
                    if _buy() and ONE_TIME_BUY:
                        log("✅ V3 buy COMPLETE!")
                        return
                    base_liq = liq
                else:
                    if base_liq > 0:
                        remaining = threshold - liq
                        log(f"⏳ V3 waiting... need +{remaining} more")
                
                time.sleep(POLL_SECONDS)
            except Exception as e:
                set_error(e)
                log(f"⚠️ V3 monitor error: {e}")
                time.sleep(1)
    except Exception as e:
        set_error(e)
        log(f"❌ V3 monitor setup FAIL: {e}")

# ==================== FIND EXISTING ====================
def find_existing_pools():
    found_v2, found_v3 = "", None
    try:
        f2 = w3.eth.contract(address=V2_FACTORY, abi=V2_FACTORY_ABI)
        pair = f2.functions.getPair(TOKEN, WETH).call()
        if pair and pair.lower() != ZERO_ADDR:
            found_v2 = Web3.to_checksum_address(pair)
            log(f"ℹ️ V2 pair pehle se mojood: {found_v2}")
    except Exception as e:
        log(f"⚠️ V2 lookup fail: {e}")
    try:
        f3 = w3.eth.contract(address=V3_FACTORY, abi=V3_FACTORY_ABI)
        for fee in FEE_TIERS:
            pool = f3.functions.getPool(TOKEN, WETH, fee).call()
            if pool and pool.lower() != ZERO_ADDR:
                found_v3 = (Web3.to_checksum_address(pool), fee)
                log(f"ℹ️ V3 pool pehle se mojood (fee {fee}): {found_v3[0]}")
                break
    except Exception as e:
        log(f"⚠️ V3 lookup fail: {e}")
    return found_v2, found_v3

# ==================== MAIN ====================
def main():
    global w3, acct, v2_router, v3_router

    if not (PRIVATE_KEY.startswith("0x") and len(PRIVATE_KEY) == 66):
        log("❌ PRIV_KEY sahi nahi.")
        return

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)

    try:
        chain_id = w3.eth.chain_id
    except Exception as e:
        log(f"❌ RPC connect fail: {e}")
        return
    if chain_id != CHAIN_ID:
        log(f"❌ RPC Base chain nahi (chain_id={chain_id}).")
        return

    acct = w3.eth.account.from_key(PRIVATE_KEY)
    balance = w3.eth.get_balance(acct.address)
    status["wallet"] = acct.address
    status["eth_balance"] = float(w3.from_wei(balance, "ether"))
    log(f"💼 Wallet: {acct.address}")
    log(f"💰 ETH balance: {status['eth_balance']:.5f} ETH")
    
    required_eth = BUY_AMOUNT_ETH + 0.005
    if balance < w3.to_wei(required_eth, "ether"):
        log(f"⚠️ ETH kam hai! Kam se kam {required_eth:.4f} ETH chahiye")
    else:
        log(f"✅ ETH sufficient!")

    v2_router = w3.eth.contract(address=V2_ROUTER, abi=V2_ROUTER_ABI)
    v3_router = w3.eth.contract(address=V3_ROUTER, abi=V3_ROUTER_ABI)

    existing_v2, existing_v3 = find_existing_pools()

    threads = []
    
    if V2_PAIR:
        try:
            status["found_v2_pair"] = Web3.to_checksum_address(V2_PAIR)
            log(f"📌 V2 manual pair: {status['found_v2_pair']}")
            t = threading.Thread(target=monitor_v2, args=(status["found_v2_pair"],), daemon=True)
            threads.append(t)
        except Exception as e:
            log(f"❌ V2_PAIR ghalat: {e}")
    elif AUTO_V2 and existing_v2:
        status["found_v2_pair"] = existing_v2
        log(f"📌 V2 existing pair: {existing_v2}")
        t = threading.Thread(target=monitor_v2, args=(existing_v2,), kwargs={"buy_now": True}, daemon=True)
        threads.append(t)
    elif AUTO_V2:
        log("🔎 V2 AUTO-MODE: Factory se pair dhoondh raha hoon...")
        t = threading.Thread(target=watch_v2_factory, daemon=True)
        threads.append(t)
    
    if V3_POOL:
        try:
            status["found_v3_pool"] = Web3.to_checksum_address(V3_POOL)
            log(f"📌 V3 manual pool: {status['found_v3_pool']}")
            t = threading.Thread(target=monitor_v3, args=(status["found_v3_pool"],), daemon=True)
            threads.append(t)
        except Exception as e:
            log(f"❌ V3_POOL ghalat: {e}")
    elif AUTO_V3 and existing_v3:
        status["found_v3_pool"] = existing_v3[0]
        log(f"📌 V3 existing pool: {existing_v3[0]} (fee {existing_v3[1]})")
        t = threading.Thread(target=monitor_v3, args=(existing_v3[0],), kwargs={"fee": existing_v3[1]}, daemon=True)
        threads.append(t)
    elif AUTO_V3:
        log("🔎 V3 AUTO-MODE: Factory se pool dhoondh raha hoon...")
        t = threading.Thread(target=watch_v3_factory, daemon=True)
        threads.append(t)
    
    if not threads:
        log("❌ Kuch bhi monitor nahi ho raha!")
        set_error("Nothing to watch")
        return

    status["mode"] = "auto (factory)" if not (V2_PAIR or V3_POOL) else "manual"
    
    log(f"🚀 Starting {len(threads)} threads...")
    for i, t in enumerate(threads, 1):
        t.start()
        time.sleep(0.1)
        log(f"✅ Thread {i} started: {t.name}")

    status["running"] = True
    status["error"] = None
    save_status()
    log(f"🚀🚀🚀🚀🚀 BOT LIVE — ULTRA BUY MODE — 100% GUARANTEED BUY")
    log(f"⚡ Buy trigger: {LIQUIDITY_THRESHOLD_PERCENT}% (ULTRA LOW)")
    log(f"⏱ Check frequency: Every {POLL_SECONDS} second (FASTEST)")
    log(f"💰 Buy amount: {BUY_AMOUNT_ETH} ETH")
    log(f"⚠️ TAX: 25% - you get 75%")
    log(f"📉 Slippage: {SLIPPAGE_PERCENT}% (MAX)")
    log(f"⛽ Gas: {MAX_FEE_GWEI} gwei (HIGH)")
    log(f"🔄 Buy attempts: {MAX_BUY_ATTEMPTS} (MAX)")

    try:
        while any(t.is_alive() for t in threads):
            if ONE_TIME_BUY and bought.is_set():
                log("🎉🎉🎉🎉🎉 BUY COMPLETE! Bot stopping.")
                break
            time.sleep(3)
    except KeyboardInterrupt:
        log("Bot band ho raha hai...")

    status["running"] = False
    save_status()
    log("🏁 Bot stopped.")

if __name__ == "__main__":
    main()