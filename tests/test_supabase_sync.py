from haa.supabase_sync import config_from_secrets


def test_config_requires_both_public_connection_values():
    assert config_from_secrets({}) is None
    assert config_from_secrets({"supabase": {"url": "https://example.supabase.co"}}) is None


def test_config_reads_public_connection_values():
    assert config_from_secrets(
        {
            "supabase": {
                "url": "https://example.supabase.co",
                "publishable_key": "sb_publishable_example",
            }
        }
    ) == ("https://example.supabase.co", "sb_publishable_example")
