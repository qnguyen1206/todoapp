# Controlled testnet wallet

Wallet version 2 creates one deterministic EVM address for each verified TODO App
account and supports tightly controlled Base Sepolia native-ETH transfers. It
runs as an internal CVM service and derives/signs through `/var/run/dstack.sock`.

The wallet currently:

- uses Base Sepolia testnet by default (chain ID `84532`);
- displays a receive address, QR code, native ETH balance, and recent history;
- creates existing users' wallets lazily when they first open the Wallet tab;
- stores only public wallet metadata in PostgreSQL; and
- prepares an immutable transfer quote before requesting authorization;
- requires password reauthentication and a short-lived email code;
- signs only simple Base Sepolia native-ETH transfers with no calldata;
- uses idempotency records and a per-user database nonce lock;
- enforces per-transfer, daily, hourly, gas, and quote-expiration limits; and
- has no arbitrary signing, contract, token, seed phrase, mnemonic, or private-key endpoint.

## Deployment

Build and push the three changed images:

```bash
docker build -t kairu1206/cvm-wallet:latest ./services/wallet
docker push kairu1206/cvm-wallet:latest

docker build -t kairu1206/cvm-backend:latest ./services/backend
docker push kairu1206/cvm-backend:latest

docker build -t kairu1206/cvm-webui:latest ./services/web_ui
docker push kairu1206/cvm-webui:latest
```

Then redeploy the updated `docker-compose.yml`. The wallet has no public port.
The backend and Web UI access it internally at `http://wallet:5004`.

The defaults work without new secrets. Optional environment variables are:

```text
WALLET_NAMESPACE=todoapp-wallet
WALLET_DERIVATION_VERSION=v1
WALLET_CHAIN_ID=84532
WALLET_CHAIN_NAME=Base Sepolia
WALLET_NATIVE_SYMBOL=ETH
WALLET_RPC_URL=https://sepolia.base.org
WALLET_EXPLORER_API_URL=https://base-sepolia.blockscout.com/api/v2
WALLET_EXPLORER_URL=https://base-sepolia.blockscout.com
WALLET_SEND_ENABLED=true
WALLET_MAX_TRANSFER_ETH=0.1
WALLET_DAILY_LIMIT_ETH=0.25
WALLET_MAX_FEE_GWEI=5
WALLET_QUOTE_TTL_SECONDS=600
WALLET_PREPARE_LIMIT_PER_HOUR=10
```

## Safety rules

`WALLET_NAMESPACE`, `WALLET_DERIVATION_VERSION`, chain ID, key conversion logic,
and the dstack application identity form the wallet derivation contract. Do not
change them after an address receives funds. Do not destroy and recreate the CVM
as a new application and assume the same address will be recoverable.

On every wallet load, the backend re-derives the address and compares it with the
public address stored in PostgreSQL. If the derivation identity has changed, the
Wallet tab refuses to show a deposit-ready wallet instead of silently using a
different address.

Base Sepolia assets have no real monetary value. Mainnet is intentionally blocked
in code. Version 2 cannot send tokens, call contracts, swap, bridge, sign arbitrary
messages, or let an AI initiate spending. A signed transaction is stored only long
enough to make an interrupted broadcast safely retryable, then removed after the
chain confirms or fails it.

## Health check

After deployment, open Settings and run **Check All Services**, or inspect the
container directly:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep wallet
docker exec <wallet-container-name> curl -f http://127.0.0.1:5004/health
```
