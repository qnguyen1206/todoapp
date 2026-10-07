// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title TODO App Achievements
/// @notice A deliberately non-transferable ERC-1155-compatible badge registry.
///         Only the TEE-derived issuer can mint the four application milestones.
contract TodoAchievements {
    address public immutable issuer;
    string private baseMetadataURI;

    mapping(address => mapping(uint256 => uint256)) private balances;
    mapping(address => mapping(uint256 => bool)) public earned;
    mapping(bytes32 => bool) public usedClaims;

    event TransferSingle(
        address indexed operator,
        address indexed from,
        address indexed to,
        uint256 id,
        uint256 value
    );
    event AchievementMinted(
        address indexed recipient,
        uint256 indexed achievementId,
        bytes32 indexed claimId
    );

    constructor(address issuerAddress, string memory metadataURI) {
        require(issuerAddress != address(0), "issuer required");
        issuer = issuerAddress;
        baseMetadataURI = metadataURI;
    }

    function mintAchievement(
        address recipient,
        uint256 achievementId,
        bytes32 claimId
    ) external {
        require(msg.sender == issuer, "issuer only");
        require(recipient != address(0), "recipient required");
        require(_allowedAchievement(achievementId), "unknown achievement");
        require(!usedClaims[claimId], "claim already used");
        require(!earned[recipient][achievementId], "achievement already earned");

        usedClaims[claimId] = true;
        earned[recipient][achievementId] = true;
        balances[recipient][achievementId] = 1;

        emit TransferSingle(msg.sender, address(0), recipient, achievementId, 1);
        emit AchievementMinted(recipient, achievementId, claimId);
    }

    function balanceOf(address account, uint256 id) external view returns (uint256) {
        require(account != address(0), "zero address");
        return balances[account][id];
    }

    function balanceOfBatch(
        address[] calldata accounts,
        uint256[] calldata ids
    ) external view returns (uint256[] memory values) {
        require(accounts.length == ids.length, "length mismatch");
        values = new uint256[](accounts.length);
        for (uint256 index = 0; index < accounts.length; index++) {
            values[index] = balances[accounts[index]][ids[index]];
        }
    }

    function uri(uint256) external view returns (string memory) {
        return baseMetadataURI;
    }

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == 0x01ffc9a7 || interfaceId == 0xd9b67a26;
    }

    function safeTransferFrom(address, address, uint256, uint256, bytes calldata) external pure {
        revert("badges are non-transferable");
    }

    function safeBatchTransferFrom(
        address,
        address,
        uint256[] calldata,
        uint256[] calldata,
        bytes calldata
    ) external pure {
        revert("badges are non-transferable");
    }

    function setApprovalForAll(address, bool) external pure {
        revert("badges are non-transferable");
    }

    function isApprovedForAll(address, address) external pure returns (bool) {
        return false;
    }

    function _allowedAchievement(uint256 id) private pure returns (bool) {
        return id == 1 || id == 10 || id == 50 || id == 100;
    }
}
