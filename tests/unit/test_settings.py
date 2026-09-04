from agent_eval_api.settings import Settings


def test_settings_json_representation_masks_secrets() -> None:
    settings = Settings(api_key_salt="top-secret", llm_api_key="provider-secret")

    serialized = settings.model_dump_json()

    assert "top-secret" not in serialized
    assert "provider-secret" not in serialized
    assert "**********" in serialized

