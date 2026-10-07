// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Minimal Base Sepolia native-ETH task escrow for TODO App V3.
/// The sponsor is the only completion approver. Funds cannot be redirected.
contract TaskRewardEscrow {
    enum State { None, Funded, Released, Refunded }

    struct Escrow {
        address sponsor;
        address recipient;
        uint96 amount;
        uint64 deadline;
        State state;
    }

    mapping(bytes32 => Escrow) public escrows;

    event EscrowCreated(bytes32 indexed key, address indexed sponsor, address indexed recipient, uint256 amount, uint64 deadline);
    event EscrowReleased(bytes32 indexed key, address indexed recipient, uint256 amount);
    event EscrowRefunded(bytes32 indexed key, address indexed sponsor, uint256 amount);

    error Unauthorized();
    error InvalidEscrow();
    error TransferFailed();

    function createEscrow(bytes32 key, address recipient, uint64 deadline) external payable {
        if (
            escrows[key].state != State.None || recipient == address(0) || msg.value == 0
                || msg.value > type(uint96).max || deadline <= block.timestamp
        ) {
            revert InvalidEscrow();
        }
        escrows[key] = Escrow(msg.sender, recipient, uint96(msg.value), deadline, State.Funded);
        emit EscrowCreated(key, msg.sender, recipient, msg.value, deadline);
    }

    function release(bytes32 key) external {
        Escrow storage escrow = escrows[key];
        if (escrow.state != State.Funded) revert InvalidEscrow();
        if (msg.sender != escrow.sponsor) revert Unauthorized();
        escrow.state = State.Released;
        uint256 amount = escrow.amount;
        (bool sent,) = escrow.recipient.call{value: amount}("");
        if (!sent) revert TransferFailed();
        emit EscrowReleased(key, escrow.recipient, amount);
    }

    function refund(bytes32 key) external {
        Escrow storage escrow = escrows[key];
        if (escrow.state != State.Funded || block.timestamp < escrow.deadline) revert InvalidEscrow();
        if (msg.sender != escrow.sponsor) revert Unauthorized();
        escrow.state = State.Refunded;
        uint256 amount = escrow.amount;
        (bool sent,) = escrow.sponsor.call{value: amount}("");
        if (!sent) revert TransferFailed();
        emit EscrowRefunded(key, escrow.sponsor, amount);
    }
}
