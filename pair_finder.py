# OPTIONAL TOOL — bot chalane ki zaroorat nahi
# Chalane ka tareeqa: python pair_finder.py

import os

from web3 import Web3

try:  # web3 v6
    from web3.middleware import geth_poa_middleware as POA_MIDDLEWARE
except ImportError:  # web3 v7+
    from web3.middleware import ExtraDataToPOAMiddleware as POA_MIDDLEWARE

RPC        = os.getenv("BASE_RPC", "https://mainnet.base.org")
TOKEN      = Web3.to_checksum_address("0xB095274743941e953c746F9C228DA9c18Bb6ec29")
WETH       = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
V2_FACTORY = Web3.to_checksum_address("0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6")
V3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
ZERO = "0x" + "0" * 40

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

PAIR_ABI = [
    {"name": "token0", "type": "function", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "address"}]},
    {"name": "getReserves", "type": "function", "stateMutability": "view",
     "inputs": [],
     "outputs": [{"name": "reserve0", "type": "uint112"},
                 {"name": "reserve1", "type": "uint112"},
                 {"name": "blockTimestampLast", "type": "uint32"}]},
]


def main():
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
    w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)

    f2 = w3.eth.contract(address=V2_FACTORY, abi=V2_FACTORY_ABI)
    f3 = w3.eth.contract(address=V3_FACTORY, abi=V3_FACTORY_ABI)

    print("\n========== V2 (Uniswap V2 Factory) ==========")
    # getPair khud sort karta hai, is liye order ki fikar nahi.
    pair = f2.functions.getPair(TOKEN, WETH).call()
    if pair.lower() == ZERO:
        print("V2 pair abhi BANA NAHI hai.")
    else:
        pair = Web3.to_checksum_address(pair)
        p = w3.eth.contract(address=pair, abi=PAIR_ABI)
        token0 = p.functions.token0().call()
        r0, r1, _ = p.functions.getReserves().call()
        laptop, weth = (r0, r1) if token0.lower() == TOKEN.lower() else (r1, r0)
        print(f"V2 PAIR MILA: {pair}")
        print(f"Reserves: LAPTOP={laptop / 1e18:.4f}  WETH={weth / 1e18:.4f}")

    print("\n========== V3 (Uniswap V3 Factory) ==========")
    found = False
    for fee, name in [(100, "0.01%"), (500, "0.05%"), (3000, "0.30%"), (10000, "1.00%")]:
        pool = f3.functions.getPool(TOKEN, WETH, fee).call()
        if pool.lower() != ZERO:
            found = True
            print(f"V3 POOL mila (fee {name}): {Web3.to_checksum_address(pool)}")
    if not found:
        print("Koi V3 pool abhi bana nahi hai.")

    print("\nNOTE: Agar koi pool nahi mila to bot khud dhoondh lega!")


if __name__ == "__main__":
    main()
