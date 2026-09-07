"""App-named token keys preserve secrets and metadata without network I/O."""
import pytest
from common.auth import app_keyed_tokens, token_refs, TokenResolutionError

CONFIG = {"oauth_apps": {"catalog": {"office-core": {"client_id": "client", "scopes": ["scope:read"]}}}}


def test_migration_preserves_metadata_and_uses_numbered_app_names():
    old = {"email": "user@example.com", "fixture-a": {"client_id": "client", "good_at": "2026-01-01T00:00:00Z"}, "fixture-b": {"client_id": "client"}}
    new = app_keyed_tokens(old, CONFIG)
    assert list(new) == ["email", "office-core-1", "office-core-2"]
    assert new["office-core-1"] == {"access_token": "fixture-a", "client_id": "client", "good_at": "2026-01-01T00:00:00Z"}
    assert app_keyed_tokens(new, CONFIG) == new
    assert "fixture-a" in old
    refs = token_refs(new)
    assert refs[0].token == "fixture-a"
    assert refs[0].source_key == "office-core-1"


def test_migration_does_not_overwrite_named_entry():
    old = {"office-core-1": {"access_token": "fixture-a", "client_id": "client"}, "fixture-b": {"client_id": "client"}}
    new = app_keyed_tokens(old, CONFIG)
    assert new["office-core-1"] == old["office-core-1"]
    assert new["office-core-2"]["access_token"] == "fixture-b"


def test_unknown_app_is_rejected_without_secret_in_error():
    with pytest.raises(TokenResolutionError) as exc:
        app_keyed_tokens({"fixture-secret": {"client_id": "unknown"}}, CONFIG)
    assert "fixture-secret" not in str(exc.value)


def test_named_token_health_validation_uses_nonsecret_key():
    with pytest.raises(TokenResolutionError) as exc:
        token_refs({"office-core-1": {"access_token": "fixture-secret", "client_id": "client", "good_at": "a", "bad_at": "b"}})
    assert "fixture-secret" not in str(exc.value.to_dict())


def test_file_migration_is_local_idempotent_and_private(tmp_path):
    import json
    import stat
    from scripts.migrate_token_keys import migrate
    p = tmp_path / "account.token"
    old = {"email": "user@example.com", "fixture-secret": {"client_id": "client", "bad_at": "2026-01-01T00:00:00Z"}}
    p.write_text(json.dumps(old))
    before = p.read_bytes()
    assert migrate(p, CONFIG)["changed"]
    assert p.read_bytes() == before
    assert migrate(p, CONFIG, apply=True)["applied"]
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert json.loads(p.read_text())["office-core-1"]["access_token"] == "fixture-secret"
    assert not migrate(p, CONFIG, apply=True)["changed"]


def test_import_duplicate_preserves_key_and_health(monkeypatch, tmp_path):
    from common import oauth_token_import as module
    from common.auth import VerifiedTokenIdentity
    monkeypatch.setattr(module, "verify_token_identity", lambda *a, **k: VerifiedTokenIdentity(email="user@example.com", client_id="client"))
    kwargs = dict(config=CONFIG, data_dir=tmp_path, agent_config={}, agent_config_path=tmp_path / "config.agent.json", account="test", token="fixture-secret")
    first = module.import_managed_oauth_token(**kwargs)
    first.token_data["office-core-1"]["good_at"] = "2026-01-01T00:00:00Z"
    module.save_token_file(first.token_path, first.token_data)
    second = module.import_managed_oauth_token(**kwargs)
    assert second.token_data == first.token_data
    third = module.import_managed_oauth_token(**{**kwargs, "token": "fixture-second"})
    assert third.token_data["office-core-2"]["access_token"] == "fixture-second"
