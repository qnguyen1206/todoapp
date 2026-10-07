# Task rewards and Base Sepolia achievement badges

The reward system treats XP as an application score, not currency. Every unique
task ID can award XP once. PostgreSQL is the source of truth, so finishing the
same task again from the Web UI, desktop sync, or an AI tool cannot award it
twice.

Milestones currently unlock at 1, 10, 50, and 100 completed tasks. An unlocked
achievement can optionally be minted as a non-transferable Base Sepolia badge.
The badge has no monetary value and cannot be sold or transferred.

## Default operation

Keep badge minting disabled while initially deploying:

```text
REWARD_BADGES_ENABLED=false
REWARD_BADGE_CONTRACT_ADDRESS=
REWARD_XP_PER_TASK=10
REWARD_XP_PER_LEVEL=50
```

XP and milestone tracking work while on-chain minting is disabled.

## Enable on-chain badges

1. Build and deploy the wallet/backend/Web UI once with badge minting disabled.
2. Get the TEE issuer address from inside the running CVM:

   ```bash
   docker exec <wallet-container> curl -sS \
     -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
     -X POST http://127.0.0.1:5004/v1/rewards/config -d '{}'
   ```

3. Compile `contracts/TodoAchievements.sol` with Solidity `0.8.24` and deploy it
   to Base Sepolia. Remix, Foundry, or Hardhat can be used. Constructor arguments:

   - `issuerAddress`: the returned `issuer_address`;
   - `metadataURI`: your public Web UI URL followed by
     `/api/rewards/metadata/{id}.json`.

   Keep `{id}` literally in the URI; ERC-1155 viewers replace it with the badge ID.
4. Send a small amount of Base Sepolia ETH to the issuer address for mint gas.
5. Set the same deployed contract address for the wallet and backend services:

   ```text
   REWARD_BADGES_ENABLED=true
   REWARD_BADGE_CONTRACT_ADDRESS=0xYourDeployedContract
   ```

6. Redeploy the same CVM with badge minting enabled.

The contract address and issuer derivation path are security-sensitive. Do not
change the wallet namespace, derivation version, environment, chain ID, or CVM
application identity after deploying the contract.

## Security boundaries

- The reward issuer can call only `mintAchievement(address,uint256,bytes32)`.
- Only achievement IDs 1, 10, 50, and 100 are accepted in both Python and Solidity.
- Claims are deterministic and single-use.
- A wallet can receive each achievement only once.
- Badges have no transfer or approval functionality.
- The issuer cannot spend a user's wallet funds.
- Reward minting is restricted to Base Sepolia.
- Failed broadcasts retry the exact same signed transaction.
