from minio import Minio
from minio.error import S3Error
import os
import logging
from io import BytesIO
from PIL import Image
import uuid
import json

logger = logging.getLogger(__name__)

# MinIO configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio")
MINIO_PORT = int(os.getenv("MINIO_PORT", "9000"))
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "user-profiles")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() == "true"

# Create MinIO client
minio_client = Minio(
    f"{MINIO_ENDPOINT}:{MINIO_PORT}",
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_USE_SSL
)

async def create_bucket_if_not_exists():
    """Create bucket if it doesn't exist"""
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"✅ Bucket '{MINIO_BUCKET}' created")
            
            # Set bucket policy to public read - dalam format string JSON
            policy_json = json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{MINIO_BUCKET}/*"]
                    }
                ]
            })
            minio_client.set_bucket_policy(MINIO_BUCKET, policy_json)
            logger.info(f"✅ Bucket policy set to public read")
        else:
            logger.info(f"✅ Bucket '{MINIO_BUCKET}' already exists")
    except S3Error as e:
        logger.error(f"❌ MinIO error: {e}")
        raise

async def upload_photo(file_content: bytes, filename: str, content_type: str) -> str:
    """Upload photo to MinIO and return URL"""
    try:
        # Generate unique filename
        ext = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_filename = f"{uuid.uuid4()}.{ext}"
        
        # Upload to MinIO
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=unique_filename,
            data=BytesIO(file_content),
            length=len(file_content),
            content_type=content_type
        )
        
        # Generate URL
        if MINIO_USE_SSL:
            url = f"https://{MINIO_ENDPOINT}:{MINIO_PORT}/{MINIO_BUCKET}/{unique_filename}"
        else:
            url = f"http://{MINIO_ENDPOINT}:{MINIO_PORT}/{MINIO_BUCKET}/{unique_filename}"
        
        logger.info(f"✅ Photo uploaded: {unique_filename}")
        return url, unique_filename
    except Exception as e:
        logger.error(f"❌ Failed to upload photo: {e}")
        raise

async def delete_photo(filename: str):
    """Delete photo from MinIO"""
    try:
        if filename:
            minio_client.remove_object(MINIO_BUCKET, filename)
            logger.info(f"✅ Photo deleted: {filename}")
    except Exception as e:
        logger.error(f"❌ Failed to delete photo: {e}")
        raise

def get_photo_url(filename: str) -> str:
    """Get public URL for photo"""
    if MINIO_USE_SSL:
        return f"https://{MINIO_ENDPOINT}:{MINIO_PORT}/{MINIO_BUCKET}/{filename}"
    return f"http://{MINIO_ENDPOINT}:{MINIO_PORT}/{MINIO_BUCKET}/{filename}"
