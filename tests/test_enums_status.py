from app.enums import CarStatus, ACTIVE_STATUSES


def test_four_values():
    assert [s.value for s in CarStatus] == ["未签约", "长期合约", "短期合约", "退役"]


def test_is_active():
    assert CarStatus.LONG.is_active and CarStatus.SHORT.is_active
    assert not CarStatus.UNSIGNED.is_active and not CarStatus.RETIRED.is_active
    assert set(ACTIVE_STATUSES) == {CarStatus.LONG, CarStatus.SHORT}


def test_contract_type_removed():
    import app.enums as e
    assert not hasattr(e, "ContractType")
