from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

import boto3


@dataclass
class S3Config:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str | None = None


def from_env() -> S3Config:
    endpoint = os.getenv("DF_MINIO_ENDPOINT") or os.getenv("DF_S3_ENDPOINT")
    access_key = os.getenv("DF_MINIO_ACCESS_KEY") or os.getenv("DF_S3_ACCESS_KEY")
    secret_key = os.getenv("DF_MINIO_SECRET_KEY") or os.getenv("DF_S3_SECRET_KEY")
    bucket = os.getenv("DF_MINIO_BUCKET") or os.getenv("DF_S3_BUCKET")
    region = os.getenv("DF_S3_REGION")
    if not all([endpoint, access_key, secret_key, bucket]):
        raise RuntimeError("Missing S3/MinIO environment variables")
    return S3Config(endpoint=str(endpoint), access_key=str(access_key), secret_key=str(secret_key), bucket=str(bucket), region=region)


def client(cfg: S3Config):
    sess = boto3.session.Session()
    return sess.client(
        "s3",
        endpoint_url=cfg.endpoint,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        region_name=cfg.region,
    )


def upload_bytes(cfg: S3Config, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    s3 = client(cfg)
    s3.put_object(Bucket=cfg.bucket, Key=key, Body=data, ContentType=content_type)


def presign_get(cfg: S3Config, key: str, expires: timedelta = timedelta(hours=1)) -> str:
    s3 = client(cfg)
    return s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": cfg.bucket, "Key": key},
        ExpiresIn=int(expires.total_seconds()),
    )

