#!/usr/bin/env python3

import os
import shutil
import json
import boto3
import pyvips
from dotenv import load_dotenv
import argparse
import sys

# Load environment variables from .env file
load_dotenv()

def convert_geotiff_to_iiif(
    input_geotiff,
    output_dir,
    bucket_name,
    s3_prefix,
    region_name="us-east-1",
    endpoint_url=None,
    aws_access_key_id=None,
    aws_secret_access_key=None,
    iiif_base_url=None,
    title="My GeoTIFF as IIIF",
    creator="Unknown",
    tile_and_upload=True
):
    """
    1) Converts a GeoTIFF to IIIF-compliant tile folders (static).
    2) Uploads files to S3 under s3://bucket_name/s3_prefix/.
    3) Generates a minimal IIIF Presentation API Manifest (JSON).
    
    Args:
        input_geotiff (str): Path to input GeoTIFF file.
        output_dir (str): Local output folder for IIIF tiles.
        bucket_name (str): Name of the S3 bucket.
        s3_prefix (str): Prefix (folder path in S3) for uploaded files.
        region_name (str): AWS region (default "us-east-1").
        endpoint_url (str): Optional custom endpoint (e.g., for S3-compatible storage).
        aws_access_key_id (str): AWS access key.
        aws_secret_access_key (str): AWS secret key.
        iiif_base_url (str): Base HTTPS URL that points to your S3 tile root
            (e.g. https://<bucket>.s3.amazonaws.com/<prefix>).
            This is used in the manifest to reference the tiles.
        title (str): Title of the work in the IIIF Manifest.
        creator (str): Creator/attribution in the IIIF Manifest.
        tile_and_upload (bool): Whether to tile and upload images.
    
    Returns:
        dict: A Python dict representing the IIIF Manifest.
    """

    # ------------------------------------------------------------------
    # 1) Convert GeoTIFF -> IIIF tile folders
    # ------------------------------------------------------------------
    # The "dzsave" method will create a folder structure that matches
    # the IIIF Image API (by specifying `layout="iiif"`).
    # The main directory will have:
    #     - info.json (contains image dimensions & tile info)
    #     - subfolders for each zoom level, each containing tiles
    # Example:
    #     my_image/
    #       ├─ info.json
    #       ├─ 0/
    #       ├─ 1/
    #       ├─ 2/
    #       └─ ...
    #
    # "access='sequential'" is often recommended for large images.
    # Depending on your GeoTIFF, you may need to specify `n=-1` or
    # other options to handle multi-band data.

    base_name = os.path.splitext(os.path.basename(input_geotiff))[0]
    dz_output_folder = os.path.join(output_dir, base_name)

    # Load the image regardless of the tile_and_upload flag
    image = pyvips.Image.new_from_file(input_geotiff, access="sequential")

    # Initialize the S3 session and bucket regardless of the tile_and_upload flag
    session = boto3.session.Session(
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )
    s3 = session.resource("s3", endpoint_url=endpoint_url)
    bucket = s3.Bucket(bucket_name)

    if tile_and_upload:
        # Clean up any existing folder to ensure a fresh output
        if os.path.exists(dz_output_folder):
            shutil.rmtree(dz_output_folder)

        print(f"Creating IIIF tiles from {input_geotiff} ...")
        image.dzsave(
            dz_output_folder,
            layout="iiif",
            suffix=".jpg",   # tile format (JPEG)
            overlap=0,       # overlap in pixels between tiles
            tile_size=256    # typical tile size for IIIF
        )
        print(f"IIIF tiles created at: {dz_output_folder}")

        # Modify the info.json file to use the correct @id
        info_json_path = os.path.join(dz_output_folder, "info.json")
        with open(info_json_path, 'r') as f:
            info_data = json.load(f)
        
        # Update the @id with the correct URL using environment variables
        info_data["@id"] = f"{os.getenv('AWS_IIIF_BASE_URL')}/{os.getenv('AWS_S3_PREFIX')}/{base_name}"
        
        sys.stdout.write(json.dumps(info_data, indent=2) + "\n")

        # Write the modified info.json back
        with open(info_json_path, 'w') as f:
            json.dump(info_data, f, indent=2)

        # Upload the tile folder to S3
        print(f"Uploading tiles to s3://{bucket_name}/{s3_prefix} ...")
        for root, dirs, files in os.walk(dz_output_folder):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, output_dir)
                s3_key = os.path.join(s3_prefix, relative_path).replace("\\", "/")

                bucket.upload_file(
                    local_path,
                    s3_key,
                    ExtraArgs={
                        "ContentType": content_type_from_extension(filename),
                        "ACL": "public-read"
                    }
                )
        print("Upload complete.")

    # The dzsave call produces:
    #    dz_output_folder/info.json
    # plus subfolders for each zoom level.

    # ------------------------------------------------------------------
    # 3) Read the IIIF "info.json" and create a Presentation Manifest
    # ------------------------------------------------------------------
    # For convenience, let's define the direct URL of info.json on S3
    if not iiif_base_url:
        # Fallback: try to guess an https endpoint if none given
        iiif_base_url = f"https://{bucket_name}.s3.amazonaws.com"

    # Construct the full service ID for this image
    image_service_id = f"{os.getenv('AWS_IIIF_BASE_URL')}/{os.getenv('AWS_S3_PREFIX')}/{base_name}"
    
    # Create a level 0 compliant info.json
    info_data = {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": image_service_id,  # Use the full service ID here
        "protocol": "http://iiif.io/api/image",
        "width": image.width,
        "height": image.height,
        "profile": ["http://iiif.io/api/image/2/level0.json"],
        "sizes": [
            {"width": image.width, "height": image.height}
        ],
        "tiles": [{
            "width": 256,
            "scaleFactors": [1]
        }]
    }

    # Construct manifest with correct image service URLs
    manifest_id = f"{image_service_id}/manifest.json"
    canvas_id = f"{manifest_id}/canvas/p1"
    image_annotation_id = f"{canvas_id}/image"

    manifest = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "@id": manifest_id,
        "label": title,
        "metadata": [
            {"label": "Creator", "value": creator}
        ],
        "sequences": [{
            "@type": "sc:Sequence",
            "canvases": [{
                "@type": "sc:Canvas",
                "@id": canvas_id,
                "label": "p. 1",
                "height": image.height,
                "width": image.width,
                "images": [{
                    "@type": "oa:Annotation",
                    "motivation": "sc:painting",
                    "@id": image_annotation_id,
                    "resource": {
                        "@id": f"{image_service_id}/full/full/0/default.jpg",
                        "@type": "dctypes:Image",
                        "format": "image/jpeg",
                        "height": image.height,
                        "width": image.width,
                        "service": {
                            "@context": "http://iiif.io/api/image/2/context.json",
                            "@id": image_service_id,
                            "profile": "http://iiif.io/api/image/2/level0.json"
                        }
                    },
                    "on": canvas_id
                }]
            }]
        }]
    }

    # Save the manifest
    manifest_path = os.path.join(dz_output_folder, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Save the info.json
    info_json_path = os.path.join(dz_output_folder, "info.json")
    with open(info_json_path, "w", encoding="utf-8") as f:
        json.dump(info_data, f, indent=2)

    # ------------------------------------------------------------------
    # 4) Save and upload the info.json and manifest.json to S3
    # ------------------------------------------------------------------
    # Upload info.json
    info_json_s3_key = os.path.join(s3_prefix, base_name, "info.json").replace("\\", "/")
    bucket.upload_file(
        info_json_path,
        info_json_s3_key,
        ExtraArgs={
            "ContentType": "application/json",
            "ACL": "public-read"
        }
    )

    # Upload manifest.json
    manifest_s3_key = os.path.join(s3_prefix, base_name, "manifest.json").replace("\\", "/")
    bucket.upload_file(
        manifest_path,
        manifest_s3_key,
        ExtraArgs={
            "ContentType": "application/json",
            "ACL": "public-read"
        }
    )

    print(f"IIIF Manifest uploaded to s3://{bucket_name}/{manifest_s3_key}")
    print(f"Public URL (if your bucket is public): {manifest_id}")

    return manifest


def content_type_from_extension(filename):
    """Basic helper to guess Content-Type from file extension."""
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in ["jpg", "jpeg"]:
        return "image/jpeg"
    elif ext == "png":
        return "image/png"
    elif ext == "json":
        return "application/json"
    elif ext == "tif" or ext == "tiff":
        return "image/tiff"
    else:
        return "binary/octet-stream"


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Convert GeoTIFF to IIIF tiles and upload to S3.")
    parser.add_argument("input_geotiff", help="Path to the input GeoTIFF file.")
    parser.add_argument("--tile_and_upload", action="store_true", help="Tile and upload images if set.")
    args = parser.parse_args()

    # Example usage
    # Adjust these variables to match your environment
    INPUT_GEOTIFF = args.input_geotiff
    OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output_tiles')
    BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', 'my-iiif-bucket')
    AWS_S3_PREFIX = os.getenv('AWS_S3_PREFIX', 'my_geotiff')
    AWS_IIIF_BASE_URL = os.getenv('AWS_IIIF_BASE_URL', 'https://my-iiif-bucket.s3.amazonaws.com/my_geotiff')

    # Load AWS credentials from .env file
    AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    REGION_NAME = os.getenv('AWS_REGION', 'us-east-1')

    convert_geotiff_to_iiif(
        input_geotiff=INPUT_GEOTIFF,
        output_dir=OUTPUT_DIR,
        bucket_name=BUCKET_NAME,
        s3_prefix=AWS_S3_PREFIX,
        region_name=REGION_NAME,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        iiif_base_url=AWS_IIIF_BASE_URL,
        title="Sample GeoTIFF",
        creator="ACME Drones",
        tile_and_upload=args.tile_and_upload
    )
