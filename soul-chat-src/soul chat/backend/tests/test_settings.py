

# ---------------------------------------------------------------------------
# operator-facing metadata
# ---------------------------------------------------------------------------
def test_every_meta_key_is_a_real_setting():
    """A typo in SETTINGS_META would silently ship an unknown toggle."""
    from app.services.settings_service import DEFAULTS, SETTINGS_META

    unknown = set(SETTINGS_META) - set(DEFAULTS)
    assert unknown == set(), f"meta keys with no matching setting: {unknown}"


def test_enforcement_levels_are_from_a_fixed_vocabulary():
    from app.services.settings_service import SETTINGS_META

    allowed = {"enforced", "reactive", "advisory"}
    for key, meta in SETTINGS_META.items():
        assert meta["enforcement"] in allowed, key
        assert meta["label"].strip(), key
        assert meta["note"].strip(), key


def test_copy_enabled_is_documented_as_advisory_only():
    """The Bot API cannot reject a silently copied message — say so plainly."""
    from app.services.settings_service import SETTINGS_META

    assert SETTINGS_META["topic.copy_enabled"]["enforcement"] == "advisory"
    # the two switches we *can* act on must not be labelled advisory
    assert SETTINGS_META["topic.forward_enabled"]["enforcement"] == "enforced"
    assert SETTINGS_META["topic.reactions_enabled"]["enforcement"] == "reactive"


async def test_settings_endpoint_returns_items_and_meta(client):
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200

    body = response.json()
    assert "items" in body
    assert "meta" in body
    assert body["meta"]["topic.copy_enabled"]["enforcement"] == "advisory"
    # every advertised key exists in the payload
    assert set(body["meta"]) <= set(body["items"])