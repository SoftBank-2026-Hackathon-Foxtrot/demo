"""A storage client made while no credentials could be found is dropped, not kept for good."""

import pytest
from botocore.exceptions import NoCredentialsError

from app import objroute


class Client:
    def __init__(self, works: bool):
        self.works = works
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        if not self.works:
            raise NoCredentialsError()
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if not self.works:
            raise NoCredentialsError()
        body = self.objects[(Bucket, Key)]
        return {"Body": type("B", (), {"read": lambda self: body})()}


def store_with(clients):
    made = []

    def opener(e):
        client = clients[len(made)]
        made.append(client)
        return client

    store = objroute.Store("http://object-migration.internal:8080", app="test", opener=opener)
    endpoint = {"kind": "s3", "bucket": "receipts", "region": "ap-northeast-2"}
    store.migration = "om-1"
    store.route = {"generation": 3, "phase": "COMPLETED", "write": endpoint, "read": [endpoint]}
    return store, made


def test_a_client_without_credentials_is_made_again():
    store, made = store_with([Client(works=False), Client(works=True)])

    with pytest.raises(NoCredentialsError):
        store.put("receipts/a.json", b"{}")
    assert store.put("receipts/a.json", b"{}") == "receipts"
    assert store.get("receipts/a.json") == (b"{}", "receipts")
    assert len(made) == 2


def test_a_read_without_credentials_drops_the_client_too():
    store, made = store_with([Client(works=False), Client(works=True)])

    with pytest.raises(NoCredentialsError):
        store.get("receipts/a.json")
    store.put("receipts/a.json", b"{}")
    assert len(made) == 2
