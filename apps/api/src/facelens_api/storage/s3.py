"""S3-compatible object storage (AWS S3, MinIO, R2...).

The bucket must be private with Block Public Access on. Objects are written with
server-side encryption. A bucket lifecycle rule (1 day) is the backstop for the
retention sweeper; see docs/RUNBOOK.md. Clients never get bucket URLs: result
images are streamed through the API behind short-lived HMAC-signed links.
"""

from __future__ import annotations

from typing import Any

from facelens_api.storage.base import BlobNotFoundError, validate_key


class S3BlobStore:
    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        client: Any | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        sse: str = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint_url,
                config=Config(retries={"max_attempts": 3, "mode": "standard"}),
            )
        self._s3 = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._sse = sse
        self._kms_key_id = kms_key_id

    def _key(self, key: str) -> str:
        validate_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, content_type: str) -> None:
        extra: dict[str, str] = {}
        if self._sse != "none":
            extra["ServerSideEncryption"] = self._sse
        if self._sse == "aws:kms" and self._kms_key_id:
            extra["SSEKMSKeyId"] = self._kms_key_id
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=data,
            ContentType=content_type,
            CacheControl="no-store",
            **extra,
        )

    def get(self, key: str) -> bytes:
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(key))
        except self._s3.exceptions.NoSuchKey:
            raise BlobNotFoundError(key) from None
        body: bytes = obj["Body"].read()
        return body

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=self._key(key))

    def delete_prefix(self, prefix: str) -> int:
        full = self._key(prefix).rstrip("/") + "/"
        removed = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if not objects:
                continue
            resp = self._s3.delete_objects(
                Bucket=self.bucket, Delete={"Objects": objects, "Quiet": True}
            )
            if resp.get("Errors"):
                raise RuntimeError(f"failed to delete {len(resp['Errors'])} objects")
            removed += len(objects)
        return removed

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

    def healthcheck(self) -> bool:
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except Exception:
            return False
        return True
