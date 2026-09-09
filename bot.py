import os
import time
import json
import threading
from datetime import datetime, timezone

from web3 import Web3

try:  # web3 v6
    from web3.middleware import geth_poa_middleware as POA_MIDDLEWARE
except ImportError:  # web3 v7+
    from web3.middleware import ExtraDataToPOAMiddleware as POA_MIDDLEWARE

# ==================== CONFIG (Railway Variables se aata hai) ====================
RPC_URL     = os.getenv("BASE_RPC", "https://mainnet.base.org")
PRIVATE_KEY = os.getenv("PRIV_KEY", "").strip()
TOKEN       = Web3.to_checksum_address("0xB095274743941e953c746F9C228DA9c18Bb6ec29")
WETH        = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
CHAIN_ID    = 8453

# Base chain par verified Uniswap addresses
V2_ROUTER  = Web3.to_checksum_address("0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24")   # V2 Router02
V3_ROUTER  = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")   # V3 SwapRouter02
V2_FACTORY = Web3.to_checksum_address("0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6")   # V2 Factory
V3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")   # V3 Factory

# Agar pair address pata ho to yahan dalein, warna khaali chhor dein (AUTO MODE chalega)
V2_PAIR = os.getenv("V2_PAIR_ADDRESS", "").strip()
V3_POOL = os.getenv("V3_POOL_ADDRESS", "").strip()
AUTO_V2 = os.getenv("AUTO_DETECT_V2", "true").lower() == "true"
AUTO_V3 = os.getenv("AUTO_DETECT_V3", "true").lower() == "true"
V3_POOL_FEE = int(os.getenv("V3_POOL_FEE", "3000"))   # 3000 = 0.30% fee tier

BUY_AMOUNT_ETH    = float(os.getenv("BUY_AMOUNT_ETH", "0.005"))
SLIPPAGE_PERCENT  = float(os.getenv("SLIPPAGE_PERCENT", "20"))
MAX_FEE_GWEI      = float(os.getenv("MAX_FEE_GWEI", "100"))
MAX_PRIORITY_GWEI = float(os.getenv("MAX_PRIORITY_GWEI", "10"))
ONE_TIME_BUY      = os.getenv("ONE_TIME_BUY", "true").lower() == "true"
POLL_SECONDS      = float(os.getenv("POLL_SECONDS", "0.5"))

STATUS_FILE = os.getenv("STATUS_FILE", "bot_status.json")
BUYS_FILE   = os.getenv("BUYS_FILE", "buys.json")

# ==================== ABIs (web3.py sirf JSON ABI leta hai) ====================
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

# SwapRouter02 (0x2626...) ki ExactInputSingleParams mein `deadline` NAHI hota.
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
    """keccak topic hex — web3 v6 ka keccak bytes deta hai (0x prefix ke bagair)."""
    h = Web3.keccak(text=text)
    h = h.hex() if not isinstance(h, str) else h
    return h if h.startswith("0x") else "0x" + h


PAIR_SIG    = _topic("PairCreated(address,address,address,uint256)")
POOL_SIG    = _topic("PoolCreated(address,address,uint24,int24,address)")
TOKEN_TOPIC = "0x" + "0" * 24 + TOKEN[2:].lower()

# ==================== GLOBALS ====================
w3 = None
acct = None
v2_router = None
v3_router = None
bought = threading.Event()      # ONE_TIME_BUY sab threads par lagu ho
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
            log(f"⚠️ status file likhne mein masla: {e}")


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
        log(f"⚠️ buys file likhne mein masla: {e}")


def _raw_tx(signed):
    """web3 v6: rawTransaction — web3 v7: raw_transaction"""
    return getattr(signed, "raw_transaction", None) or signed.rawTransaction


def _gas_fields():
    return {
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "chainId": CHAIN_ID,
        "maxFeePerGas": w3.to_wei(MAX_FEE_GWEI, "gwei"),
        "maxPriorityFeePerGas": w3.to_wei(MAX_PRIORITY_GWEI, "gwei"),
    }


def _send(tx, version):
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(_raw_tx(signed)).hex()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    log(f"TX bhej di: {tx_hash}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] == 1:
        log(f"✅ {version} BUY SUCCESS: https://basescan.org/tx/{tx_hash}")
        return tx_hash
    log(f"❌ {version} buy revert ho gaya: {tx_hash}")
    return None


# ==================== BUY FUNCTIONS ====================
def buy_v2(amount_in_wei):
    path = [WETH, TOKEN]
    amounts = v2_router.functions.getAmountsOut(amount_in_wei, path).call()
    expected_out = amounts[-1]
    amount_out_min = int(expected_out * (100 - SLIPPAGE_PERCENT) / 100)
    log(f"V2 quote: {expected_out / 10**18:.2f} token expected")

    tx = v2_router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        amount_out_min, path, acct.address, int(time.time()) + 120
    ).build_transaction({"from": acct.address, "value": amount_in_wei, "gas": 400000, **_gas_fields()})
    return _send(tx, "V2")


def buy_v3(amount_in_wei, fee=None):
    fee = V3_POOL_FEE if fee is None else fee
    # SwapRouter02: (tokenIn, tokenOut, fee, recipient, amountIn, amountOutMinimum, sqrtPriceLimitX96)
    params = (WETH, TOKEN, int(fee), acct.address, amount_in_wei, 0, 0)
    tx = v3_router.functions.exactInputSingle(params).build_transaction(
        {"from": acct.address, "value": amount_in_wei, "gas": 500000, **_gas_fields()})
    return _send(tx, "V3")


def try_buy(fn, amount_wei, version):
    if ONE_TIME_BUY and bought.is_set():
        return False
    for attempt in range(1, 4):
        log(f"🛒 {version} buy attempt {attempt}/3 ...")
        try:
            tx_hash = fn(amount_wei)
            if tx_hash:
                add_buy(tx_hash, version)
                bought.set()
                return True
        except Exception as e:
            log(f"⚠️ Buy attempt {attempt} fail: {e}")
            set_error(e)
        time.sleep(2)
    log(f"❌ {version} buy 3 dafa fail hua.")
    return False


# ==================== LOG PARSING HELPERS ====================
def _data_hex(entry):
    """log data ko hamesha '0x...' string bana kar deta hai (v6 HexBytes deta hai)."""
    data = entry["data"]
    if isinstance(data, (bytes, bytearray)):
        return "0x" + bytes(data).hex()
    return data if data.startswith("0x") else "0x" + data


def _word(data_hex, index):
    """data ka n-va 32-byte word (64 hex chars)."""
    start = 2 + 64 * index
    return data_hex[start:start + 64]


def _addr_from_word(word):
    return Web3.to_checksum_address("0x" + word[24:])


# ==================== FACTORY WATCHERS (AUTO MODE) ====================
def _scan(factory_addr, sig, from_block, to_block):
    """Dono topic positions (token0 ya token1) check karta hai."""
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
    log("🔎 V2 AUTO-MODE: Uniswap Factory se naya LAPTOP pair dhoondh raha hoon...")
    last = w3.eth.block_number
    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            cur = w3.eth.block_number
            if cur > last:
                entry = _scan(V2_FACTORY, PAIR_SIG, last + 1, cur)
                last = cur
                if entry:
                    # PairCreated data: [0]=pair, [1]=allPairsLength
                    pair = _addr_from_word(_word(_data_hex(entry), 0))
                    log(f"🆕 NAYA V2 PAIR BANA: {pair}")
                    status["found_v2_pair"] = pair
                    save_status()
                    monitor_v2(pair, buy_now=True)
                    return
            else:
                last = cur
            time.sleep(1)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V2 factory watcher error: {e}")
            time.sleep(2)


def watch_v3_factory():
    log("🔎 V3 AUTO-MODE: Uniswap V3 Factory se naya LAPTOP pool dhoondh raha hoon...")
    last = w3.eth.block_number
    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            cur = w3.eth.block_number
            if cur > last:
                entry = _scan(V3_FACTORY, POOL_SIG, last + 1, cur)
                last = cur
                if entry:
                    # PoolCreated data: [0]=tickSpacing, [1]=pool  (fee 3rd indexed topic hai)
                    data = _data_hex(entry)
                    pool = _addr_from_word(_word(data, 1))
                    fee = V3_POOL_FEE
                    topics = entry["topics"]
                    if len(topics) > 3:
                        raw = topics[3]
                        fee = int(raw.hex() if not isinstance(raw, str) else raw, 16)
                    log(f"🆕 NAYA V3 POOL BANA: {pool} (fee {fee})")
                    status["found_v3_pool"] = pool
                    save_status()
                    monitor_v3(pool, fee=fee)
                    return
            else:
                last = cur
            time.sleep(1)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V3 factory watcher error: {e}")
            time.sleep(2)


# ==================== PAIR/POOL MONITORS ====================
def monitor_v2(pair_address, buy_now=False):
    pair = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=V2_PAIR_ABI)
    token0 = pair.functions.token0().call()
    is_token0 = token0.lower() == TOKEN.lower()
    log(f"V2 pair: {pair_address} | LAPTOP token0 hai: {is_token0}")

    r0, r1, _ = pair.functions.getReserves().call()
    base_reserve = r0 if is_token0 else r1
    log(f"👀 V2 current reserve: {base_reserve / 10**18:.4f} LAPTOP")

    if buy_now and base_reserve > 10**15:
        log("💧 V2 pair + liquidity dono mojood — FORAN BUY!")
        if try_buy(buy_v2, w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V2") and ONE_TIME_BUY:
            return
    base_reserve = max(base_reserve, 1)

    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            r0, r1, _ = pair.functions.getReserves().call()
            reserve = r0 if is_token0 else r1
            if reserve > base_reserve * 1.2:
                log("💧 V2 LIQUIDITY INCREASE DETECTED!")
                if try_buy(buy_v2, w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V2") and ONE_TIME_BUY:
                    return
                base_reserve = reserve
            time.sleep(POLL_SECONDS)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V2 monitor error: {e}")
            time.sleep(2)


def monitor_v3(pool_address, fee=None):
    fee = V3_POOL_FEE if fee is None else fee
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=V3_POOL_ABI)
    base_liq = pool.functions.liquidity().call()
    log(f"👀 V3 pool: {pool_address} | fee: {fee} | current liquidity: {base_liq}")

    def _buy():
        return try_buy(lambda amt: buy_v3(amt, fee), w3.to_wei(BUY_AMOUNT_ETH, "ether"), "V3")

    while not (ONE_TIME_BUY and bought.is_set()):
        try:
            liq = pool.functions.liquidity().call()
            if (base_liq == 0 and liq > 0) or (base_liq > 0 and liq > base_liq * 1.2):
                log("💧 V3 LIQUIDITY ADD/INCREASE DETECTED!")
                if _buy() and ONE_TIME_BUY:
                    return
                base_liq = liq
            time.sleep(POLL_SECONDS)
        except Exception as e:
            set_error(e)
            log(f"⚠️ V3 monitor error: {e}")
            time.sleep(2)


def find_existing_pools():
    """Bot start hote hi dekhta hai ke pair/pool pehle se mojood to nahi."""
    found_v2, found_v3 = "", None
    try:
        f2 = w3.eth.contract(address=V2_FACTORY, abi=V2_FACTORY_ABI)
        pair = f2.functions.getPair(TOKEN, WETH).call()
        if pair and pair.lower() != ZERO_ADDR:
            found_v2 = Web3.to_checksum_address(pair)
            log(f"ℹ️ V2 pair pehle se mojood hai: {found_v2}")
    except Exception as e:
        log(f"⚠️ V2 factory lookup fail: {e}")
    try:
        f3 = w3.eth.contract(address=V3_FACTORY, abi=V3_FACTORY_ABI)
        for fee in FEE_TIERS:
            pool = f3.functions.getPool(TOKEN, WETH, fee).call()
            if pool and pool.lower() != ZERO_ADDR:
                found_v3 = (Web3.to_checksum_address(pool), fee)
                log(f"ℹ️ V3 pool pehle se mojood hai (fee {fee}): {found_v3[0]}")
                break
    except Exception as e:
        log(f"⚠️ V3 factory lookup fail: {e}")
    return found_v2, found_v3


# ==================== MAIN ====================
def main():
    global w3, acct, v2_router, v3_router

    if not (PRIVATE_KEY.startswith("0x") and len(PRIVATE_KEY) == 66):
        log("❌ PRIV_KEY sahi nahi. Railway Variables mein 0x... wali private key dalein.")
        return

    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)

    try:
        chain_id = w3.eth.chain_id
    except Exception as e:
        log(f"❌ RPC se connect nahi ho saka: {e}")
        return
    if chain_id != CHAIN_ID:
        log(f"❌ RPC Base chain ka nahi (chain_id={chain_id}). BASE_RPC check karein.")
        return

    acct = w3.eth.account.from_key(PRIVATE_KEY)
    balance = w3.eth.get_balance(acct.address)
    status["wallet"] = acct.address
    status["eth_balance"] = float(w3.from_wei(balance, "ether"))   # Decimal JSON-safe nahi hai
    log(f"Wallet: {acct.address}")
    log(f"ETH balance: {status['eth_balance']:.5f} ETH")
    if balance < w3.to_wei(BUY_AMOUNT_ETH + 0.002, "ether"):
        log("⚠️ ETH kam hai (buy amount + gas ke liye ~0.01 ETH chahiye).")

    v2_router = w3.eth.contract(address=V2_ROUTER, abi=V2_ROUTER_ABI)
    v3_router = w3.eth.contract(address=V3_ROUTER, abi=V3_ROUTER_ABI)

    existing_v2, existing_v3 = find_existing_pools()

    threads = []
    if V2_PAIR:
        try:
            status["found_v2_pair"] = Web3.to_checksum_address(V2_PAIR)
        except Exception as e:
            log(f"❌ V2_PAIR_ADDRESS ghalat: {e}")
            return
        threads.append(threading.Thread(target=monitor_v2,
                                        args=(status["found_v2_pair"],), daemon=True))
    elif AUTO_V2 and existing_v2:
        status["found_v2_pair"] = existing_v2
        threads.append(threading.Thread(target=monitor_v2, args=(existing_v2,),
                                        kwargs={"buy_now": True}, daemon=True))
    elif AUTO_V2:
        threads.append(threading.Thread(target=watch_v2_factory, daemon=True))

    if V3_POOL:
        try:
            status["found_v3_pool"] = Web3.to_checksum_address(V3_POOL)
            threads.append(threading.Thread(target=monitor_v3,
                                            args=(status["found_v3_pool"],), daemon=True))
        except Exception as e:
            log(f"❌ V3_POOL_ADDRESS ghalat: {e}")
    elif AUTO_V3 and existing_v3:
        status["found_v3_pool"] = existing_v3[0]
        threads.append(threading.Thread(target=monitor_v3, args=(existing_v3[0],),
                                        kwargs={"fee": existing_v3[1]}, daemon=True))
    elif AUTO_V3:
        threads.append(threading.Thread(target=watch_v3_factory, daemon=True))

    if not threads:
        log("❌ Kuch bhi watch nahi ho raha. AUTO_DETECT_V2=true rakhein ya pair address dalein.")
        set_error("Nothing to watch")
        return

    status["mode"] = "auto (factory)" if not (V2_PAIR or V3_POOL) else "manual (pair set)"
    for t in threads:
        t.start()

    status["running"] = True
    status["error"] = None
    save_status()
    log(f"🚀 BOT LIVE — mode: {status['mode']} — liquidity ka intezaar...")

    try:
        while any(t.is_alive() for t in threads):
            if ONE_TIME_BUY and bought.is_set():
                log("✅ Buy ho chuki hai, ONE_TIME_BUY on hai — band kar raha hoon.")
                break
            time.sleep(5)
    except KeyboardInterrupt:
        log("Bot band ho raha hai...")

    status["running"] = False
    save_status()
    log("🏁 Kaam khatam. Bot band.")


if __name__ == "__main__":
    main()
