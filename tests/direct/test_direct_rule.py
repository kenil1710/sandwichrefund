"""SandwichRefund in GenLayer's Direct Mode (genlayer-test): the deployed
bytes (build/SandwichRefund.py) run on the official SDK; the two RPCs are
mocked by body. Covers the verdict, validator agreement and disagreement,
RPC failures and disagreement between the RPCs, and the recovery window."""
import json

from conftest import BLOCK, ETH, GEN, RPC_A, RPC_B, VICTIM, Chain, h32, warp


def case(contract, pid, h):
    return contract.get_pool_case(pid, "ethereum", h)


def test_sandwich_is_refunded(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    r = contract.file_case(pool, "ethereum", v)
    assert r["state"] == "SANDWICHED_REFUNDED", r
    assert r["loss"] == str(3 * ETH // 100)
    assert r["refund"] == str(3 * GEN // 10)
    c = case(contract, pool, v)
    assert c["victim"] == VICTIM and c["final"] is True


def test_validator_agrees_on_the_same_data(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    assert direct_vm.run_validator() is True


def test_validator_disagrees_when_its_rpcs_answer_differently(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    for lg in net.a.logs:                       # the validator's view of the back-run differs
        if lg["transactionIndex"] == "0x2":
            lg["data"] = lg["data"][:-1] + "7"
    assert direct_vm.run_validator() is False


def test_validator_rejects_a_forged_leader_result(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    stored = direct_vm._captured_validators[-1][0]
    forged = json.loads(json.dumps(stored))
    forged["facts"]["tx"]["from"] = "0x" + "9" * 40
    assert direct_vm.run_validator(leader_result=forged) is False


def test_validator_rejects_a_leader_claiming_unreadable(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    assert direct_vm.run_validator(leader_result={"reason": "RPC_UNREADABLE", "detail": "x"}) is False


def test_validator_rejects_a_leader_error(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


def test_rpc_down_is_unverifiable_and_pending(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.down.add(RPC_B)
    r = contract.file_case(pool, "ethereum", v)
    assert (r["state"], r["reason"]) == ("UNVERIFIABLE", "RPC_UNREADABLE")
    assert contract.get_pool(pool, 0)["pending"] == 1
    assert direct_vm.run_validator() is True    # both sides unreadable: agreed, nothing paid


def test_rpcs_disagree(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.b = Chain()                              # the second RPC does not have the block
    r = contract.file_case(pool, "ethereum", v)
    assert (r["state"], r["reason"]) == ("UNVERIFIABLE", "RPC_DISAGREE")


def test_rpc_error_answer(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.a.status = 500
    r = contract.file_case(pool, "ethereum", v)
    assert r["reason"] == "RPC_UNREADABLE"


def test_not_final_is_unverifiable(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.a.finalized = BLOCK
    r = contract.file_case(pool, "ethereum", v)
    assert (r["state"], r["reason"]) == ("UNVERIFIABLE", "NOT_FINALIZED")


def test_clean_swap(direct_vm, net, contract, pool):
    v = net.a.tx(VICTIM, "0x" + "1" * 40, 5 * ETH, -450 * ETH, VICTIM, 1)
    r = contract.file_case(pool, "ethereum", v)
    assert r["state"] == "NOT_COVERED"
    from conftest import ROUTER
    v2 = net.a.tx(VICTIM, ROUTER, 5 * ETH, -450 * ETH, VICTIM, 5)
    assert contract.file_case(pool, "ethereum", v2)["state"] == "CLEAN"


def test_decided_case_cannot_be_filed_twice(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    contract.file_case(pool, "ethereum", v)
    with direct_vm.expect_revert("ALREADY_DECIDED_SANDWICHED_REFUNDED"):
        contract.file_case(pool, "ethereum", v)


def test_recovery_window_retry_then_close(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.down.add(RPC_A)
    contract.file_case(pool, "ethereum", v)
    net.down.clear()
    warp(direct_vm, "2026-10-21T01:30:00Z")      # past the 1 h claim period, inside the 1 h recovery window
    with direct_vm.expect_revert("RECOVERY_WINDOW_OPEN_UNTIL"):
        contract.close_pool(pool)
    with direct_vm.expect_revert("CLAIM_PERIOD_OVER"):
        contract.file_case(pool, "ethereum", h32("new"))
    assert contract.file_case(pool, "ethereum", v)["state"] == "SANDWICHED_REFUNDED"
    assert contract.get_pool(pool, 0)["pending"] == 0
    assert contract.close_pool(pool)["expired"] == 0


def test_recovery_window_over_expires(direct_vm, net, contract, pool):
    v = net.a.sandwich()
    net.down.add(RPC_A)
    contract.file_case(pool, "ethereum", v)
    warp(direct_vm, "2026-10-21T02:30:00Z")      # past the recovery window too
    with direct_vm.expect_revert("RECOVERY_WINDOW_OVER"):
        contract.file_case(pool, "ethereum", v)
    assert contract.close_pool(pool)["expired"] == 1
    c = case(contract, pool, v)
    assert c["state"] == "EXPIRED" and c["final"] is True


def test_junk_never_holds_a_pool_open(direct_vm, net, contract, pool):
    for i in range(3):
        assert contract.file_case(pool, "ethereum", h32(("junk", i)))["reason"] == "TX_NOT_FOUND"
    warp(direct_vm, "2026-10-21T01:01:00Z")
    assert contract.close_pool(pool)["ok"] is True
