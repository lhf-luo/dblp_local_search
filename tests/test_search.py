from dblp_local_search.search.models import Search
from dblp_local_search.search.service import search


def test_and_or_not_and_phrase(client):
    body = {
        "query": {
            "all_of": [{"text": "graph learning", "field": "title"}],
            "none_of": [{"text": "survey"}],
        }
    }
    result = client.post("/v1/papers/search", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 2
    body["query"]["all_of"][0]["phrase"] = True
    assert client.post("/v1/papers/search", json=body).json()["total"] == 1
    body = {"query": {"any_of": [{"text": "Survey"}, {"text": "Security"}]}}
    assert client.post("/v1/papers/search", json=body).json()["total"] == 2


def test_year_venue_and_negative_without_positive_text(client):
    result = client.post(
        "/v1/papers/search",
        json={
            "year_from": 2024,
            "year_to": 2024,
            "venues": ["ICSE"],
            "query": {"none_of": [{"text": "survey"}]},
        },
    )
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["authors"] == ["Alice Smith", "René Jones"]


def test_pagination_and_changed_query(client):
    body = {"query": {"all_of": [{"text": "graph"}]}, "page_size": 1}
    first = client.post("/v1/papers/search", json=body).json()
    assert first["next_cursor"]
    second = client.post(
        "/v1/papers/search", json={**body, "cursor": first["next_cursor"]}
    ).json()
    assert first["items"][0]["dblp_key"] != second["items"][0]["dblp_key"]
    changed = {**body, "year_from": 2024, "cursor": first["next_cursor"]}
    assert client.post("/v1/papers/search", json=changed).status_code == 422


def test_lookup_and_author_identity(client):
    lookup = client.get("/v1/papers/lookup", params={"key": "conf/icse/One24"}).json()
    assert lookup["items"][0]["doi"] == "10.1234/one"
    result = client.get("/v1/authors/search", params={"name": "Alice"}).json()
    author = result["items"][0]
    assert author["pid"] == "s/Alice" and author["identity_verified"]
    papers = client.get(f"/v1/authors/{author['author_id']}/papers")
    assert papers.status_code == 200, papers.text
    assert papers.json()["total"] == 2
    unverified = client.get("/v1/authors/search", params={"name": "René"}).json()
    assert not unverified["items"][0]["identity_verified"]


def test_bad_input(client):
    assert client.post("/v1/papers/search", json={}).status_code == 422
    assert (
        client.post(
            "/v1/papers/search", json={"query": {"all_of": [{"text": "++"}]}}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/papers/search", json={"year_from": 2025, "year_to": 2020}
        ).status_code
        == 422
    )
    assert client.get("/health/ready").status_code == 200
    assert client.get("/v1/papers/lookup").status_code == 422
    assert (
        client.get("/v1/papers/lookup", params={"key": "missing"}).json()["items"] == []
    )


def test_no_total_and_safe_punctuation(populated):
    result = search(
        populated,
        Search.model_validate(
            {
                "query": {"all_of": [{"text": 'Graph" OR 1=1 --'}]},
                "include_total": False,
            }
        ),
    )
    assert result["total"] is None
    assert result["items"] == []
