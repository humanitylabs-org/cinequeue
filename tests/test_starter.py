import json
from cinequeue.starter import initialize


def test_new_install_has_exact_public_example(tmp_path):
    p = tmp_path / 'movies.json'
    initialize(p)
    records = json.loads(p.read_text())
    assert len(records) == 1
    assert records[0]['title'] == 'Batman Begins'
    assert records[0]['imdb_id'] == 'tt0372784'
    assert records[0]['runtime_minutes'] == 140
    assert not records[0]['watch_history']
    before = p.read_bytes()
    initialize(p)
    assert p.read_bytes() == before


def test_preserves_populated_and_deliberately_emptied_owner_store(tmp_path):
    p = tmp_path / 'movies.json'
    for data in [[], [{'id':'owner-film','notes':'private', 'watch_history':[{'watched_on':'2026-01-01'}]}]]:
        p.write_text(json.dumps(data))
        before = p.read_bytes()
        initialize(p)
        assert p.read_bytes() == before
