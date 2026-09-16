from outreach.synthetic import generate_discharge_feed


def test_bulk_feed_is_reproducible_and_fhir_shaped() -> None:
    first = generate_discharge_feed(25, seed=9)
    second = generate_discharge_feed(25, seed=9)
    assert first == second
    assert len(first) == 25
    assert all(item["synthetic"] is True for item in first)
    assert all(item["patient"]["resourceType"] == "Patient" for item in first)
    assert all(item["encounter"]["resourceType"] == "Encounter" for item in first)


def test_bulk_feed_enforces_prototype_limit() -> None:
    for count in (0, 501):
        try:
            generate_discharge_feed(count)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid synthetic feed size was accepted")
