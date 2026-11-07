"""Order receipts in S3-compatible storage. Keys never change, so the object is written first
and the DB row names it afterwards, and a read that misses the primary bucket falls back.

With OBJECT_MIGRATION_SERVER set, a migration of the receipt bucket decides where to write and
read (objroute.py); without one in progress, S3_BUCKET and S3_FALLBACK_BUCKET below."""
import json
import os

from . import objroute

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = os.environ.get("S3_BUCKET", "receipts-aws")
FALLBACK_BUCKET = os.environ.get("S3_FALLBACK_BUCKET", "receipts-gcp")
_client = None
# Followed from start-up in every process, with or without traffic: the migration server waits
# for every app that asks, and must hear from this one before it moves writes.
route = objroute.Store(os.environ["OBJECT_MIGRATION_SERVER"]) if os.environ.get("OBJECT_MIGRATION_SERVER") else None
if route:
    route.start()


class ReceiptMissing(Exception):
    pass


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None, region_name=os.environ.get("S3_REGION", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, connect_timeout=1, read_timeout=10,
                          retries={"max_attempts": 1},
                          # GCS rejects the CRC headers newer SDKs add to every upload by default.
                          request_checksum_calculation="when_required",
                          response_checksum_validation="when_required"))
    return _client


def key_of(request_id: str) -> str:
    return f"receipts/{request_id}.json"


def ensure_buckets():
    for bucket in (BUCKET, FALLBACK_BUCKET):
        try:
            client().head_bucket(Bucket=bucket)
        except ClientError:
            client().create_bucket(Bucket=bucket)


def put(request_id: str, receipt: dict) -> str:
    key = key_of(request_id)
    body = json.dumps(receipt, ensure_ascii=False).encode()
    if route and route.following():
        route.put(key, body, "application/json")
        return key
    client().put_object(Bucket=BUCKET, Key=key, Body=body,
                        ContentType="application/json")
    return key


def get(key: str) -> tuple[dict, str]:
    """The receipt and the bucket it came from. An outage of both raises the client's own error."""
    if route and route.following():
        try:
            body, bucket = route.get(key)
        except objroute.NotFound as e:
            raise ReceiptMissing(key) from e
        return json.loads(body), bucket
    failure: Exception | None = None
    for bucket in (BUCKET, FALLBACK_BUCKET):
        try:
            return json.loads(client().get_object(Bucket=bucket, Key=key)["Body"].read()), bucket
        except Exception as e:  # noqa: BLE001  a miss or an outage here: try the other bucket
            failure = e
    if isinstance(failure, ClientError) and failure.response["Error"]["Code"] in ("NoSuchKey", "404"):
        raise ReceiptMissing(key)
    raise failure
